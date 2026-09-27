from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from omarchy_focus.bar import render_bar
from omarchy_focus.database import Database
from omarchy_focus.focus_hosts_helper import HostsStatus
from omarchy_focus.models import FocusStateSnapshot
from omarchy_focus.services.focus import FocusService
from omarchy_focus.services.pomodoro import PomodoroService
from omarchy_focus.services.stats import StatsService
from omarchy_focus.services.tasks import TaskService
from omarchy_focus.settings import SettingsService
from omarchy_focus.utils import utc_now


class ServiceFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "focus.db")
        self.db.initialize()
        self.settings = SettingsService(self.db)
        self.tasks = TaskService(self.db)
        self.focus = FocusService(self.db, self.settings)
        self.pomodoro = PomodoroService(self.db, self.settings, self.tasks, self.focus)
        self.stats = StatsService(self.db)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_task_crud_and_listing(self) -> None:
        task = self.tasks.add_task(
            "Write docs",
            priority="high",
            tags="docs release",
            estimated_minutes=45,
        )
        listed = self.tasks.list_tasks()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].id, task.id)
        updated = self.tasks.update_task(task.id, status="in_progress")
        self.assertEqual(updated.status.value, "in_progress")
        done = self.tasks.complete_task(task.id, notifications_enabled=False)
        self.assertEqual(done.status.value, "done")

    def test_reopening_task_clears_completion_timestamp(self) -> None:
        task = self.tasks.add_task("Ship release")
        task = self.tasks.complete_task(task.id, notifications_enabled=False)
        self.assertIsNotNone(task.completed_at)
        reopened = self.tasks.update_task(task.id, status="pending")
        self.assertEqual(reopened.status.value, "pending")
        self.assertIsNone(reopened.completed_at)

    def test_task_optional_fields_can_be_cleared_explicitly(self) -> None:
        task = self.tasks.add_task(
            "Schedule launch",
            estimated_minutes=45,
            due_at="2026-09-01 10:00",
        )
        updated = self.tasks.update_task(
            task.id,
            clear_estimated_minutes=True,
            clear_due_at=True,
        )
        self.assertIsNone(updated.estimated_minutes)
        self.assertIsNone(updated.due_at)

    def test_blocked_site_edit_and_toggle(self) -> None:
        self.focus.add_site("example.com", enabled=False)
        sites = dict((domain, enabled) for domain, enabled, _ in self.focus.list_sites())
        self.assertFalse(sites["example.com"])

        updated = self.focus.update_site("example.com", new_domain="docs.example.com", enabled=True)
        self.assertEqual(updated, "docs.example.com")

        sites = dict((domain, enabled) for domain, enabled, _ in self.focus.list_sites())
        self.assertNotIn("example.com", sites)
        self.assertTrue(sites["docs.example.com"])

        self.focus.toggle_site("docs.example.com", False)
        sites = dict((domain, enabled) for domain, enabled, _ in self.focus.list_sites())
        self.assertFalse(sites["docs.example.com"])

    def test_blocked_site_changes_reapply_active_focus(self) -> None:
        active_focus = FocusStateSnapshot(
            active=True,
            session_id="focus123",
            strict_mode=False,
            blocked_sites=("reddit.com",),
            started_at=utc_now(),
            auto_release=True,
        )
        self.focus._persist_snapshot(active_focus)
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO focus_sessions (
                    session_id, strict_mode, started_at, ends_at,
                    active, blocked_sites_json, auto_release, recovered, notes
                ) VALUES (?, 0, ?, NULL, 1, '["reddit.com"]', 1, 0, '')
                """,
                ("focus123", "2026-04-13T10:00:00+00:00"),
            )

        with patch.object(
            self.focus,
            "_run_helper",
            return_value=HostsStatus(active=True, session_id="focus123", sites=("example.com", "reddit.com")),
        ) as helper:
            self.focus.add_site("example.com")

        helper.assert_called_once()
        persisted = self.focus.snapshot()
        self.assertEqual(persisted.blocked_sites, ("example.com", "reddit.com"))

    def test_pomodoro_pause_resume_stop(self) -> None:
        task = self.tasks.add_task("Deep work")
        snapshot = self.pomodoro.start(task_id=task.id, minutes=1, auto_focus=False)
        self.assertEqual(snapshot.task_id, task.id)
        paused = self.pomodoro.pause()
        self.assertEqual(paused.phase.value, "paused")
        resumed = self.pomodoro.resume()
        self.assertEqual(resumed.phase.value, "running")
        stopped = self.pomodoro.stop(reason="test complete")
        self.assertEqual(stopped.phase.value, "idle")

    def test_pomodoro_statistics_exclude_multiple_pauses(self) -> None:
        started = datetime(2026, 9, 27, 10, tzinfo=UTC)
        with patch("omarchy_focus.services.pomodoro.utc_now", return_value=started):
            self.pomodoro.start(minutes=15, auto_focus=False)
        for pause_minute, resume_minute, seconds_left in [(5, 10, 600), (15, 20, 300)]:
            with (
                patch("omarchy_focus.services.pomodoro.utc_now", return_value=started + timedelta(minutes=pause_minute)),
                patch("omarchy_focus.services.pomodoro.remaining_seconds", return_value=seconds_left),
            ):
                self.pomodoro.pause()
            with patch("omarchy_focus.services.pomodoro.utc_now", return_value=started + timedelta(minutes=resume_minute)):
                self.pomodoro.resume()
        with (
            patch("omarchy_focus.services.pomodoro.utc_now", return_value=started + timedelta(minutes=25)),
            patch("omarchy_focus.services.pomodoro.remaining_seconds", return_value=0),
            patch("omarchy_focus.services.pomodoro.play_alert_sound"),
            patch("omarchy_focus.services.pomodoro.focus_app_tui"),
        ):
            self.pomodoro.tick()
        row = self.db.fetchone("SELECT duration_seconds, completed FROM pomodoro_sessions")
        self.assertEqual(row["duration_seconds"], 15 * 60)
        self.assertEqual(row["completed"], 1)

    def test_pomodoro_start_rolls_back_when_focus_fails(self) -> None:
        # Intentionally assert on a broad Exception: the point of this test is
        # that *any* failure inside start() triggers a full rollback.
        with (
            patch.object(self.focus, "start", side_effect=Exception("boom")),
            self.assertRaises(Exception),  # noqa: B017 - rollback-on-any-error
        ):
            self.pomodoro.start(minutes=1, auto_focus=True)
        self.assertIsNone(self.pomodoro._load_raw())

    def test_work_completion_creates_pending_break_prompt(self) -> None:
        task = self.tasks.add_task("Deep work")
        with (
            patch("omarchy_focus.services.pomodoro.play_alert_sound") as play_sound,
            patch("omarchy_focus.services.pomodoro.focus_app_tui") as focus_tui,
        ):
            self.pomodoro.start(task_id=task.id, minutes=1, auto_focus=False)
            raw = self.pomodoro._load_raw()
            assert raw is not None
            raw["ends_at"] = "2000-01-01T00:00:00+00:00"
            raw["remaining_seconds"] = 0
            self.pomodoro._save_raw(raw)
            snapshot = self.pomodoro.tick()

        self.assertEqual(snapshot.phase.value, "idle")
        pending_break = self.pomodoro.pending_break()
        self.assertIsNotNone(pending_break)
        assert pending_break is not None
        self.assertEqual(int(pending_break["minutes"]), 10)
        self.assertEqual(pending_break["task_title"], task.title)
        self.assertIsNone(self.pomodoro._load_raw())
        play_sound.assert_called_once()
        focus_tui.assert_called_once()

        break_snapshot = self.pomodoro.start_break()
        self.assertEqual(break_snapshot.phase.value, "running")
        self.assertEqual(break_snapshot.session_type.value, "short_break")
        self.assertIsNone(self.pomodoro.pending_break())

    def test_reboot_clears_active_session_and_pending_break(self) -> None:
        task = self.tasks.add_task("Deep work")
        with patch("omarchy_focus.services.pomodoro.current_boot_id", return_value="boot-a"):
            self.pomodoro.start(task_id=task.id, minutes=1, auto_focus=False)
            self.pomodoro._save_pending_break(
                {
                    "prompt_id": "break-a",
                    "break_type": "short_break",
                    "minutes": 10,
                    "boot_id": "boot-a",
                    "task_id": task.id,
                    "task_title": task.title,
                    "cycle_count": 1,
                    "created_at": "2026-04-13T10:00:00+00:00",
                }
            )

        with patch("omarchy_focus.services.pomodoro.current_boot_id", return_value="boot-b"):
            snapshot = self.pomodoro.status()

        self.assertEqual(snapshot.phase.value, "idle")
        self.assertIsNone(self.pomodoro._load_raw())
        self.assertIsNone(self.pomodoro.pending_break())

    def test_legacy_session_without_boot_id_is_cleared(self) -> None:
        task = self.tasks.add_task("Deep work")
        self.pomodoro._save_raw(
            {
                "phase": "running",
                "session_type": "work",
                "started_at": "2026-04-13T10:00:00+00:00",
                "ends_at": "2026-04-13T10:50:00+00:00",
                "paused_at": None,
                "remaining_seconds": 1200,
                "task_id": task.id,
                "task_title": task.title,
                "cycle_count": 0,
                "auto_focus": False,
                "strict_focus": False,
            }
        )
        with patch("omarchy_focus.services.pomodoro.current_boot_id", return_value="boot-now"):
            snapshot = self.pomodoro.status()
        self.assertEqual(snapshot.phase.value, "idle")
        self.assertIsNone(self.pomodoro._load_raw())

    def test_stats_and_bar_idle_output(self) -> None:
        class Services:
            pass

        services = Services()
        services.sync = lambda: None
        services.pomodoro = self.pomodoro
        services.focus = self.focus
        services.stats = self.stats
        services.tasks = self.tasks
        payload = render_bar(services, json_mode=False)
        self.assertIn("", payload)

    def test_stats_use_real_focus_session_count(self) -> None:
        task = self.tasks.add_task("Deep work")
        self.pomodoro.start(task_id=task.id, minutes=1, auto_focus=False)
        raw = self.pomodoro._load_raw()
        assert raw is not None
        raw["ends_at"] = "2000-01-01T00:00:00+00:00"
        raw["remaining_seconds"] = 0
        self.pomodoro._save_raw(raw)
        with (
            patch("omarchy_focus.services.pomodoro.play_alert_sound"),
            patch("omarchy_focus.services.pomodoro.focus_app_tui"),
        ):
            self.pomodoro.tick()

        snapshot = self.stats.snapshot()
        self.assertEqual(snapshot.focus_sessions_week, 0)

    def test_bar_shows_countdown_for_timed_focus(self) -> None:
        class Services:
            pass

        services = Services()
        services.sync = lambda: None
        services.pomodoro = self.pomodoro
        services.stats = self.stats
        services.tasks = self.tasks

        timed_focus = FocusStateSnapshot(
            active=True,
            strict_mode=False,
            blocked_sites=("reddit.com",),
            started_at=utc_now(),
            ends_at=utc_now(),
        )

        class FocusStub:
            def snapshot(self) -> FocusStateSnapshot:
                return timed_focus

        services.focus = FocusStub()
        payload = render_bar(services, json_mode=False)
        self.assertTrue(payload.startswith("󰈈 "))
        self.assertNotIn("Focus", payload)

    def test_schema_version_is_recorded(self) -> None:
        from omarchy_focus.database import SCHEMA_VERSION

        row = self.db.fetchone("PRAGMA user_version")
        self.assertEqual(int(row[0]), SCHEMA_VERSION)

    def test_expected_indexes_exist(self) -> None:
        rows = self.db.fetchall("SELECT name FROM sqlite_master WHERE type = 'index'")
        names = {row["name"] for row in rows}
        for expected in ("idx_tasks_status", "idx_pomodoro_lookup", "idx_focus_active"):
            self.assertIn(expected, names)

    def test_theme_setting_roundtrip(self) -> None:
        from omarchy_focus.tui.app import (
            DAYLIGHT_GOLD,
            MIDNIGHT_GOLD,
            THEME_SETTING_KEY,
            THEMES_BY_NAME,
        )

        # Default matches the dark signature theme and both themes are known.
        self.assertEqual(self.settings.get(THEME_SETTING_KEY), MIDNIGHT_GOLD.name)
        self.assertIn(MIDNIGHT_GOLD.name, THEMES_BY_NAME)
        self.assertIn(DAYLIGHT_GOLD.name, THEMES_BY_NAME)
        # The toggle persists the light theme so it survives a restart.
        self.settings.set(THEME_SETTING_KEY, DAYLIGHT_GOLD.name)
        self.assertEqual(self.settings.get(THEME_SETTING_KEY), DAYLIGHT_GOLD.name)

    def test_stats_markdown_report(self) -> None:
        from omarchy_focus.cli import _render_stats_markdown

        self.tasks.add_task("Write report")
        report = _render_stats_markdown(self.stats.snapshot())
        self.assertIn("# Clar Focus — Report", report)
        self.assertIn("## Today", report)
        self.assertIn("## This week", report)

    def test_focus_recover_preserves_state_when_hosts_unreadable(self) -> None:
        snapshot = FocusStateSnapshot(
            active=True,
            session_id="focus123",
            strict_mode=False,
            blocked_sites=("reddit.com", "www.reddit.com"),
            started_at=utc_now(),
            system_consistent=True,
            auto_release=True,
        )
        self.focus._persist_snapshot(snapshot)
        with patch(
            "omarchy_focus.services.focus.inspect_hosts_file",
            return_value=HostsStatus(active=False, readable=False),
        ):
            recovered = self.focus.recover()
        self.assertTrue(recovered.active)
        self.assertFalse(recovered.system_consistent)
        self.assertEqual(recovered.session_id, "focus123")


if __name__ == "__main__":
    unittest.main()
