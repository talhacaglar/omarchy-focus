"""Behaviour added in 0.2: break cadence, pause accounting, read-only
refreshes, hardened hosts helper, data migration, charts and widget state."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from omarchy_focus import focus_hosts_helper as helper
from omarchy_focus import paths
from omarchy_focus.bar import build_state_payload
from omarchy_focus.bootstrap import ServiceContainer
from omarchy_focus.charts import heat_level, heatmap_rows, peak_window, render_heatmap
from omarchy_focus.database import Database
from omarchy_focus.exceptions import PomodoroError
from omarchy_focus.models import SessionType
from omarchy_focus.services.focus import FocusService
from omarchy_focus.services.pomodoro import PomodoroService
from omarchy_focus.services.stats import StatsService
from omarchy_focus.services.tasks import TaskService
from omarchy_focus.settings import SettingsService
from omarchy_focus.utils import local_now, to_iso, utc_now

QUIET = (
    patch("omarchy_focus.services.pomodoro.notify"),
    patch("omarchy_focus.services.pomodoro.play_alert_sound"),
    patch("omarchy_focus.services.pomodoro.poke_status_bar"),
    patch("omarchy_focus.services.pomodoro.focus_app_tui"),
)


class ServicesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "focus.db")
        self.db.initialize()
        self.settings = SettingsService(self.db)
        self.tasks = TaskService(self.db)
        self.focus = FocusService(self.db, self.settings)
        self.pomodoro = PomodoroService(self.db, self.settings, self.tasks, self.focus)
        self.stats = StatsService(self.db)
        for quiet in QUIET:
            quiet.start()
            self.addCleanup(quiet.stop)
        self.addCleanup(self.tmpdir.cleanup)

    def finish_current_session(self) -> None:
        raw = self.pomodoro._load_raw()
        assert raw is not None
        raw["ends_at"] = to_iso(utc_now() - timedelta(seconds=1))
        self.pomodoro._save_raw(raw)
        self.pomodoro.tick()


class PomodoroCadenceTest(ServicesTestCase):
    def test_every_fourth_session_earns_a_long_break(self) -> None:
        self.settings.set("pomodoro_long_break_every", 4)
        break_types = []
        for _ in range(4):
            self.pomodoro.start(minutes=25, auto_focus=False)
            self.finish_current_session()
            pending = self.pomodoro.pending_break()
            assert pending is not None
            break_types.append((pending["break_type"], pending["minutes"]))
            self.pomodoro.skip_break()
        self.assertEqual([kind for kind, _ in break_types[:3]], ["short_break"] * 3)
        self.assertEqual(break_types[3], (SessionType.LONG_BREAK.value, 25))

    def test_cycle_resets_after_a_long_gap(self) -> None:
        self.pomodoro._set_streak(3)
        stale = json.loads(self.db.get_state(PomodoroService.STREAK_KEY)["value_json"])
        stale["updated_at"] = to_iso(utc_now() - timedelta(hours=5))
        self.db.upsert_state(PomodoroService.STREAK_KEY, json.dumps(stale))
        self.assertEqual(self.pomodoro._current_streak(), 0)

    def test_skip_break_requires_a_pending_break(self) -> None:
        with self.assertRaises(PomodoroError):
            self.pomodoro.skip_break()


class PomodoroAccountingTest(ServicesTestCase):
    def test_paused_time_is_not_counted_as_focus(self) -> None:
        self.pomodoro.start(minutes=50, auto_focus=False)
        raw = self.pomodoro._load_raw()
        assert raw is not None
        start = utc_now() - timedelta(minutes=30)
        raw["started_at"] = to_iso(start)
        raw["ends_at"] = to_iso(start + timedelta(minutes=50))
        self.pomodoro._save_raw(raw)
        self.pomodoro.pause()
        raw = self.pomodoro._load_raw()
        raw["paused_at"] = to_iso(utc_now() - timedelta(minutes=20))
        self.pomodoro._save_raw(raw)
        snapshot = self.pomodoro.resume()
        self.assertGreaterEqual(snapshot.paused_seconds, 20 * 60 - 2)
        self.pomodoro.stop()
        row = self.db.fetchone("SELECT duration_seconds FROM pomodoro_sessions")
        # 30 minutes elapsed, 20 of them paused.
        self.assertLess(row["duration_seconds"], 11 * 60)
        self.assertGreater(row["duration_seconds"], 9 * 60)

    def test_running_tick_does_not_write(self) -> None:
        self.pomodoro.start(minutes=25, auto_focus=False)
        with patch.object(self.db, "upsert_state") as upsert:
            snapshot = self.pomodoro.tick()
        upsert.assert_not_called()
        self.assertGreater(snapshot.remaining_seconds, 24 * 60)
        self.assertEqual(snapshot.total_seconds, 25 * 60)

    def test_completed_session_records_planned_end(self) -> None:
        self.pomodoro.start(minutes=25, auto_focus=False)
        self.finish_current_session()
        row = self.db.fetchone("SELECT ended_at, completed FROM pomodoro_sessions")
        self.assertEqual(row["completed"], 1)
        self.assertIsNotNone(row["ended_at"])


class DatabaseTest(unittest.TestCase):
    def test_removed_default_site_stays_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "focus.db")
            db.initialize()
            db.execute("DELETE FROM blocked_sites WHERE domain = 'reddit.com'")
            db.initialize()
            self.assertIsNone(db.fetchone("SELECT 1 FROM blocked_sites WHERE domain = 'reddit.com'"))

    def test_settings_startup_is_read_only_once_seeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "focus.db")
            db.initialize()
            SettingsService(db)
            with patch.object(db, "seed_defaults") as seed:
                SettingsService(db)
            seed.assert_not_called()


class HostsHelperHardeningTest(unittest.TestCase):
    def test_domain_validation(self) -> None:
        for good in ("reddit.com", "www.youtube.com", "a-b.co.uk", "xn--bcher-kva.example"):
            self.assertTrue(helper.is_valid_domain(good), good)
        for bad in (
            "reddit.com\n1.2.3.4 evil",
            "# comment",
            "-a.com",
            "a..com",
            "localhost",
            "1.2.3.4",
            "a b.com",
        ):
            self.assertFalse(helper.is_valid_domain(bad), bad)

    def test_apply_rejects_injection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hosts = Path(tmpdir) / "hosts"
            hosts.write_text("127.0.0.1 localhost\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                helper.main(
                    [
                        "--hosts-file",
                        str(hosts),
                        "apply",
                        "--session-id",
                        "abc",
                        "--started-at",
                        "now",
                        "reddit.com\n6.6.6.6 bank.com",
                    ]
                )
            self.assertEqual(hosts.read_text(encoding="utf-8"), "127.0.0.1 localhost\n")

    def test_elevated_callers_cannot_redirect_writes(self) -> None:
        with (
            patch.object(helper.os, "geteuid", return_value=0),
            patch.dict(helper.os.environ, {"SUDO_UID": "1000"}),
            self.assertRaises(SystemExit),
        ):
            helper.main(["--hosts-file", "/tmp/not-hosts", "clear"])


class MigrationTest(unittest.TestCase):
    def test_legacy_database_is_copied_not_moved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy = root / "data" / "clar-focus"
            legacy.mkdir(parents=True)
            with sqlite3.connect(legacy / "focus.db") as conn:
                conn.execute("CREATE TABLE marker (value TEXT)")
                conn.execute("INSERT INTO marker VALUES ('kept')")
            (legacy / "venv").mkdir()
            (root / "config" / "clar-focus").mkdir(parents=True)
            (root / "config" / "clar-focus" / "note").write_text("hi", encoding="utf-8")
            new_db = root / "data" / "omarchy-focus" / "focus.db"
            with (
                patch.object(paths, "_DATA_ROOT", root / "data"),
                patch.object(paths, "_CONFIG_ROOT", root / "config"),
                patch.object(paths, "DB_PATH", new_db),
                patch.object(paths, "CONFIG_DIR", root / "config" / "omarchy-focus"),
            ):
                paths.migrate_legacy_data()
            with sqlite3.connect(new_db) as conn:
                self.assertEqual(conn.execute("SELECT value FROM marker").fetchone()[0], "kept")
            self.assertTrue((legacy / "focus.db").exists())
            self.assertTrue((legacy / "venv").exists())
            self.assertEqual((root / "config" / "omarchy-focus" / "note").read_text(encoding="utf-8"), "hi")


class ChartsTest(unittest.TestCase):
    def test_heat_levels_follow_goal_quarters(self) -> None:
        self.assertEqual([heat_level(m, 120) for m in (0, 10, 50, 90, 120, 300)], [0, 1, 2, 3, 4, 4])

    def test_heatmap_aligns_weekdays(self) -> None:
        # 2026-10-07 is a Wednesday: Monday and Tuesday of week one are blank.
        days = [("2026-10-07", 30), ("2026-10-08", 0), ("2026-10-09", 200)]
        _, rows = heatmap_rows(days, 100)
        self.assertIsNone(rows[0][0])
        self.assertIsNone(rows[1][0])
        self.assertEqual(rows[2][0], ("■", 1))
        self.assertEqual(rows[4][0], ("■", 4))
        self.assertIn("Mon", render_heatmap(days, 100))

    def test_peak_window(self) -> None:
        hours = [0] * 24
        hours[9], hours[10], hours[15] = 50, 40, 60
        self.assertEqual(peak_window(hours), (9, 90))
        self.assertIsNone(peak_window([0] * 24))


class StatsTest(ServicesTestCase):
    def test_daily_and_hourly_minutes(self) -> None:
        started = local_now().replace(hour=9, minute=0, second=0, microsecond=0)
        if started > local_now():
            started -= timedelta(days=1)
        self.db.execute(
            """
            INSERT INTO pomodoro_sessions (session_type, state, started_at, ended_at,
                duration_seconds, completed, interrupted)
            VALUES ('work', 'running', ?, ?, 3000, 1, 0)
            """,
            (to_iso(started), to_iso(started + timedelta(minutes=50))),
        )
        days = self.stats.daily_minutes(days=7)
        self.assertEqual(len(days), 7)
        self.assertEqual(days[-1][0], local_now().date().isoformat())
        self.assertEqual(sum(minutes for _, minutes in days), 50)
        self.assertEqual(self.stats.hourly_minutes(days=7)[9], 50)


class StatePayloadTest(ServicesTestCase):
    def test_widget_payload_shape(self) -> None:
        self.tasks.add_task("Write tests", priority="high", estimated_minutes=25)
        container = ServiceContainer(
            self.db, self.settings, self.tasks, self.focus, self.pomodoro, self.stats
        )
        with (
            patch.object(ServiceContainer, "sync", return_value=None),
            patch("omarchy_focus.bar.poke_status_bar"),
        ):
            self.pomodoro.start(minutes=25, auto_focus=False)
            payload = build_state_payload(container, heatmap_days=14)
        self.assertEqual(payload["schema"], 1)
        pomodoro = payload["pomodoro"]
        self.assertEqual(pomodoro["phase"], "running")
        self.assertEqual(pomodoro["total_seconds"], 1500)
        self.assertGreater(pomodoro["ends_at_ms"], 0)
        self.assertEqual(len(payload["heatmap"]), 14)
        self.assertEqual(payload["next_tasks"][0]["title"], "Write tests")
        self.assertEqual(payload["stats"]["goal_minutes"], 150)
        json.dumps(payload)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class PluginModelTest(unittest.TestCase):
    def test_qml_model_helpers(self) -> None:
        script = Path(__file__).with_name("test_plugin_model.mjs")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
