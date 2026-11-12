"""What the bar panel relies on: changing a running session, private arguments,
the state it reads, and its strings."""

from __future__ import annotations

import io
import json
import re
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from omarchy_focus import cli, widget
from omarchy_focus.bar import build_state_payload
from omarchy_focus.bootstrap import ServiceContainer
from omarchy_focus.database import Database
from omarchy_focus.exceptions import FocusModeError, PomodoroError
from omarchy_focus.models import FocusStateSnapshot, SessionPhase
from omarchy_focus.services.focus import FocusService
from omarchy_focus.services.pomodoro import PomodoroService
from omarchy_focus.services.stats import StatsService
from omarchy_focus.services.tasks import TaskService
from omarchy_focus.settings import SettingsService
from omarchy_focus.utils import remaining_seconds, utc_now

QUIET = (
    patch("omarchy_focus.services.pomodoro.notify"),
    patch("omarchy_focus.services.pomodoro.poke_status_bar"),
    patch("omarchy_focus.services.focus.notify"),
    patch("omarchy_focus.services.focus.poke_status_bar"),
    patch("omarchy_focus.services.pomodoro.play_alert_sound"),
)


class PanelTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.db = Database(Path(tmpdir.name) / "focus.db")
        self.db.initialize()
        self.settings = SettingsService(self.db)
        self.tasks = TaskService(self.db)
        self.focus = FocusService(self.db, self.settings)
        self.pomodoro = PomodoroService(self.db, self.settings, self.tasks, self.focus)
        self.stats = StatsService(self.db)
        self.services = ServiceContainer(
            self.db, self.settings, self.tasks, self.focus, self.pomodoro, self.stats
        )
        for quiet in QUIET:
            quiet.start()
            self.addCleanup(quiet.stop)

    def active_guard(self, *, strict: bool = False, minutes: int | None = 30) -> None:
        self.focus._persist_snapshot(
            FocusStateSnapshot(
                active=True,
                session_id="guard1",
                strict_mode=strict,
                blocked_sites=("reddit.com",),
                started_at=utc_now(),
                ends_at=utc_now() + timedelta(minutes=minutes) if minutes else None,
            )
        )


class AdjustSessionTest(PanelTestCase):
    def test_extending_moves_the_end_and_the_planned_length(self) -> None:
        self.pomodoro.start(minutes=25, auto_focus=False)
        before = self.pomodoro.snapshot()
        after = self.pomodoro.adjust(5)
        self.assertEqual(after.total_seconds, before.total_seconds + 300)
        assert before.ends_at and after.ends_at
        self.assertEqual(after.ends_at - before.ends_at, timedelta(minutes=5))
        self.assertEqual(self.pomodoro.snapshot().ends_at, after.ends_at)

    def test_shortening_stops_at_the_last_minute(self) -> None:
        self.pomodoro.start(minutes=10, auto_focus=False)
        after = self.pomodoro.adjust(-60)
        self.assertLessEqual(remaining_seconds(after.ends_at), 60)
        self.assertGreater(remaining_seconds(after.ends_at), 50)
        self.assertEqual(self.pomodoro.snapshot().phase, SessionPhase.RUNNING)
        # Already in the last minute: nothing left to take away.
        again = self.pomodoro.adjust(-1)
        self.assertEqual(again.ends_at, after.ends_at)

    def test_a_paused_session_keeps_its_time_until_resumed(self) -> None:
        self.pomodoro.start(minutes=20, auto_focus=False)
        paused = self.pomodoro.pause()
        adjusted = self.pomodoro.adjust(10)
        self.assertEqual(adjusted.remaining_seconds, paused.remaining_seconds + 600)
        self.assertIsNone(adjusted.ends_at)
        resumed = self.pomodoro.resume()
        self.assertGreater(remaining_seconds(resumed.ends_at), paused.remaining_seconds + 590)

    def test_length_has_a_ceiling(self) -> None:
        self.pomodoro.start(minutes=25, auto_focus=False)
        after = self.pomodoro.adjust(100_000)
        self.assertLessEqual(after.remaining_seconds, PomodoroService.MAX_ADJUSTED_SECONDS)

    def test_nothing_to_adjust_when_idle(self) -> None:
        with self.assertRaises(PomodoroError):
            self.pomodoro.adjust(5)

    def test_extended_session_records_its_real_length(self) -> None:
        self.pomodoro.start(minutes=10, auto_focus=False)
        self.pomodoro.adjust(5)
        raw = self.pomodoro._load_raw()
        assert raw is not None
        started = utc_now() - timedelta(minutes=15, seconds=1)
        raw["started_at"] = started.isoformat()
        raw["ends_at"] = (started + timedelta(minutes=15)).isoformat()
        self.pomodoro._save_raw(raw)
        self.pomodoro.tick()
        row = self.db.fetchone("SELECT duration_seconds, completed FROM pomodoro_sessions")
        self.assertEqual(row["duration_seconds"], 15 * 60)
        self.assertEqual(row["completed"], 1)

    def test_a_linked_guard_follows_the_session(self) -> None:
        self.active_guard(minutes=25)
        self.pomodoro.start(minutes=25, auto_focus=False)
        raw = self.pomodoro._load_raw()
        assert raw is not None
        raw["auto_focus"] = True
        self.pomodoro._save_raw(raw)
        after = self.pomodoro.adjust(10)
        self.assertEqual(self.focus.snapshot().ends_at, after.ends_at)

    def test_an_unlinked_guard_stays_where_it_is(self) -> None:
        self.active_guard(minutes=25)
        before = self.focus.snapshot().ends_at
        self.pomodoro.start(minutes=25, auto_focus=False)
        self.pomodoro.adjust(10)
        self.assertEqual(self.focus.snapshot().ends_at, before)

    def test_strict_session_cannot_be_shortened(self) -> None:
        self.pomodoro.start(minutes=25, auto_focus=False)
        raw = self.pomodoro._load_raw()
        assert raw is not None
        raw.update(auto_focus=True, strict_focus=True)
        self.pomodoro._save_raw(raw)
        with self.assertRaises(PomodoroError):
            self.pomodoro.adjust(-5)
        self.pomodoro.adjust(5)

    def test_starting_with_a_guard_already_on_leaves_it_alone(self) -> None:
        self.active_guard(minutes=90)
        before = self.focus.snapshot()
        with patch.object(self.focus, "start") as start_guard:
            snapshot = self.pomodoro.start(minutes=25, auto_focus=True)
        start_guard.assert_not_called()
        self.assertFalse(snapshot.auto_focus)
        self.pomodoro.stop()
        self.assertEqual(self.focus.snapshot().ends_at, before.ends_at)


class AssignTaskTest(PanelTestCase):
    def test_assigning_keeps_the_clock_running(self) -> None:
        task = self.tasks.add_task("Draft")
        started = self.pomodoro.start(minutes=25, auto_focus=False)
        after = self.pomodoro.assign_task(task.id)
        self.assertEqual(after.task_title, "Draft")
        self.assertEqual(after.ends_at, started.ends_at)
        self.assertEqual(self.tasks.get_task(task.id).status, "in_progress")
        self.assertIsNone(self.db.fetchone("SELECT id FROM pomodoro_sessions"))
        self.assertIsNone(self.pomodoro.assign_task(None).task_id)

    def test_nothing_to_assign_when_idle(self) -> None:
        with self.assertRaises(PomodoroError):
            self.pomodoro.assign_task(None)


class AdjustGuardTest(PanelTestCase):
    def test_extending_and_shortening_a_timed_guard(self) -> None:
        self.active_guard(minutes=30)
        before = self.focus.snapshot().ends_at
        assert before
        self.assertEqual(self.focus.adjust(5).ends_at - before, timedelta(minutes=5))
        short = self.focus.adjust(-600)
        self.assertLessEqual(remaining_seconds(short.ends_at), 60)
        self.assertGreater(remaining_seconds(short.ends_at), 50)

    def test_an_expired_guard_counts_from_now(self) -> None:
        self.active_guard(minutes=30)
        snapshot = self.focus.snapshot()
        snapshot.ends_at = utc_now() - timedelta(minutes=10)
        self.focus._persist_snapshot(snapshot)
        self.assertGreater(remaining_seconds(self.focus.adjust(5).ends_at), 290)

    def test_strict_guard_only_gets_longer(self) -> None:
        self.active_guard(strict=True)
        with self.assertRaises(FocusModeError):
            self.focus.adjust(-5)
        self.focus.adjust(5)

    def test_refused_without_a_timer_or_a_guard(self) -> None:
        with self.assertRaises(FocusModeError):
            self.focus.adjust(5)
        self.active_guard(minutes=None)
        with self.assertRaises(FocusModeError):
            self.focus.adjust(5)


class OpenEndedSessionTest(PanelTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.t0 = utc_now()

    def at(self, minutes: float):
        return patch(
            "omarchy_focus.services.pomodoro.utc_now", return_value=self.t0 + timedelta(minutes=minutes)
        )

    def recorded(self):
        return self.db.fetchall("SELECT duration_seconds, completed, interrupted FROM pomodoro_sessions")

    def test_counts_up_without_an_end(self) -> None:
        with self.at(0):
            snapshot = self.pomodoro.start(open_ended=True, auto_focus=False)
        self.assertTrue(snapshot.open_ended)
        self.assertIsNone(snapshot.ends_at)
        self.assertEqual(snapshot.total_seconds, 0)
        # Hours later it is still running: nothing ends it but a stop.
        with self.at(300):
            self.assertEqual(self.pomodoro.tick().phase, SessionPhase.RUNNING)
        self.assertEqual(self.recorded(), [])

    def test_saved_length_zero_starts_without_a_timer(self) -> None:
        self.settings.set("pomodoro_work_minutes", 0)
        self.assertTrue(self.pomodoro.start(auto_focus=False).open_ended)
        # An explicit length still wins.
        self.assertFalse(self.pomodoro.start(minutes=25, auto_focus=False).open_ended)

    def test_stopping_records_a_finished_session(self) -> None:
        with self.at(0):
            self.pomodoro.start(open_ended=True, auto_focus=False)
        with self.at(10):
            self.pomodoro.pause()
        with self.at(15):
            self.pomodoro.resume()
            self.assertIsNone(self.pomodoro.snapshot().ends_at)
        with self.at(42):
            self.pomodoro.stop()
        [row] = self.recorded()
        self.assertEqual((row["duration_seconds"], row["completed"], row["interrupted"]), (37 * 60, 1, 0))
        # No break is queued: the user decided when to stop.
        self.assertIsNone(self.pomodoro.pending_break())

    def test_a_misclick_is_not_focus_time(self) -> None:
        with self.at(0):
            self.pomodoro.start(open_ended=True, auto_focus=False)
        with self.at(0.5):
            self.pomodoro.stop()
        [row] = self.recorded()
        self.assertEqual((row["completed"], row["interrupted"]), (0, 1))

    def test_has_no_timer_to_change(self) -> None:
        self.pomodoro.start(open_ended=True, auto_focus=False)
        with self.assertRaises(PomodoroError):
            self.pomodoro.adjust(5)

    def test_guard_stays_on_until_the_session_stops(self) -> None:
        self.settings.set("strict_mode_default", True)
        with patch.object(self.focus, "start") as start_guard:
            snapshot = self.pomodoro.start(open_ended=True, auto_focus=True)
        start_guard.assert_called_once_with(minutes=None, strict_mode=False)
        self.assertFalse(snapshot.strict_focus)

    def test_payload_carries_what_the_panel_counts_from(self) -> None:
        with self.at(0):
            self.pomodoro.start(open_ended=True, auto_focus=False)
        with (
            self.at(7),
            patch.object(ServiceContainer, "sync", return_value=None),
            patch("omarchy_focus.bar.poke_status_bar"),
        ):
            state = build_state_payload(self.services, heatmap_days=7)["pomodoro"]
        self.assertTrue(state["open_ended"])
        self.assertIsNone(state["ends_at_ms"])
        self.assertEqual(state["started_at_ms"], int(self.t0.timestamp() * 1000))
        self.assertEqual(state["elapsed_seconds"], 7 * 60)

    def test_cli_takes_open_ended_or_minutes_not_both(self) -> None:
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["start", "--open-ended", "--minutes", "5"])
        self.assertTrue(cli.build_parser().parse_args(["start", "--open-ended"]).open_ended)


class SettingsValidationTest(PanelTestCase):
    def test_values_are_checked(self) -> None:
        self.settings.set("pomodoro_work_minutes", 25)
        self.assertEqual(self.settings.get("pomodoro_work_minutes"), 25)
        self.settings.set("pomodoro_work_minutes", 0)  # no timer
        self.assertEqual(self.settings.get("pomodoro_work_minutes"), 0)
        for key, value in (
            ("pomodoro_work_minutes", -1),
            ("pomodoro_work_minutes", 721),
            ("pomodoro_work_minutes", "soon"),
            ("notifications_enabled", 1),
            ("no_such_setting", 1),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.settings.set(key, value)

    def test_settings_of_the_old_terminal_app_are_dropped(self) -> None:
        self.db.set_setting("theme_variant", json.dumps("midnight-gold"))
        self.db.set_setting("open_app_on_complete", json.dumps(True))
        values = SettingsService(self.db).all()
        self.assertNotIn("theme_variant", values)
        self.assertNotIn("open_app_on_complete", values)


class StatePayloadTest(PanelTestCase):
    def payload(self) -> dict:
        with (
            patch.object(ServiceContainer, "sync", return_value=None),
            patch("omarchy_focus.bar.poke_status_bar"),
        ):
            return build_state_payload(self.services, heatmap_days=14)

    def test_panel_gets_every_task_site_and_setting(self) -> None:
        task = self.tasks.add_task(
            "Report",
            description="Q4",
            priority="high",
            tags="work, docs",
            estimated_minutes=50,
            due_at="2026-12-01",
        )
        done = self.tasks.add_task("Finished")
        self.tasks.complete_task(done.id, notifications_enabled=False)
        archived = self.tasks.add_task("Shelved")
        self.tasks.update_task(archived.id, status="archived")
        self.db.execute(
            """INSERT INTO pomodoro_sessions (task_id, session_type, state, started_at, ended_at,
               duration_seconds, completed, interrupted, notes)
               VALUES (?, 'work', 'running', ?, ?, 1500, 0, 1, '')""",
            (task.id, utc_now().isoformat(), utc_now().isoformat()),
        )
        payload = self.payload()
        self.assertEqual(payload["schema"], 2)
        rows = {row["title"]: row for row in payload["tasks"]}
        self.assertEqual(set(rows), {"Report", "Finished", "Shelved"})
        report = rows["Report"]
        self.assertEqual(report["tags"], ["docs", "work"])
        self.assertEqual(report["estimate"], 50)
        self.assertEqual(report["focus_minutes"], 25)
        self.assertEqual(report["due"], "2026-12-01 00:00")
        self.assertIsInstance(report["due_at_ms"], int)
        self.assertEqual(payload["tasks"][0]["title"], "Report")  # open tasks first
        self.assertIn("reddit.com", {site["domain"] for site in payload["sites"]})
        self.assertEqual(payload["settings"]["guard_minutes"], 50)
        self.assertIn("focus_auto_release", payload["settings"])
        self.assertIn("passwordless_guard", payload)

    def test_stats_cover_the_whole_page(self) -> None:
        stats = self.payload()["stats"]
        self.assertEqual(len(stats["hours"]), 24)
        for key in ("top_tasks", "blocked_sites", "peak_start", "week_tasks_done", "week_sessions_cut"):
            self.assertIn(key, stats)

    def test_edit_can_clear_estimate_and_due(self) -> None:
        task = self.tasks.add_task("Report", estimated_minutes=50, due_at="2026-12-01")
        updated = self.tasks.update_task(task.id, clear_estimated_minutes=True, clear_due_at=True)
        self.assertIsNone(updated.estimated_minutes)
        self.assertIsNone(updated.due_at)


class ArgsFromStdinTest(PanelTestCase):
    def run_cli(self, *args: str, stdin: str = "") -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with (
            patch("omarchy_focus.cli.build_services", return_value=self.services),
            patch("omarchy_focus.cli.poke_status_bar"),
            patch("sys.stdin", io.StringIO(stdin)),
            patch("sys.stdout", out),
            patch("sys.stderr", err),
        ):
            try:
                code = cli.main(list(args))
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 2
                if not isinstance(exc.code, int):
                    err.write(str(exc.code))
        return code, out.getvalue(), err.getvalue()

    def run_stdin(self, *args: str) -> tuple[int, str, str]:
        return self.run_cli(cli.ARGS_FROM_STDIN, stdin=json.dumps(list(args)) + "\n")

    def test_runs_the_command_it_reads(self) -> None:
        code, out, _ = self.run_stdin("add-task", "--priority", "high", "--", "Ödev teslim et")
        self.assertEqual(code, 0, out)
        task = self.tasks.list_open()[0]
        self.assertEqual((task.title, task.priority), ("Ödev teslim et", "high"))

    def test_a_title_that_looks_like_an_option_is_a_title(self) -> None:
        self.assertEqual(self.run_stdin("add-task", "--priority", "low", "--", "--version")[0], 0)
        task = self.tasks.list_open()[0]
        self.assertEqual(task.title, "--version")
        code = self.run_stdin(
            "tasks", "edit", str(task.id), "--title=--help", "--description=-x", "--clear-due"
        )[0]
        self.assertEqual(code, 0)
        task = self.tasks.get_task(task.id)
        self.assertEqual((task.title, task.description), ("--help", "-x"))

    def test_signed_minutes_reach_adjust(self) -> None:
        self.pomodoro.start(minutes=25, auto_focus=False)
        before = self.pomodoro.snapshot().ends_at
        assert before
        self.assertEqual(self.run_stdin("adjust", "-5")[0], 0)
        self.assertEqual(before - self.pomodoro.snapshot().ends_at, timedelta(minutes=5))
        self.assertEqual(self.run_cli("adjust", "5")[0], 0)
        self.assertEqual(self.pomodoro.snapshot().ends_at, before)

    def test_domain_commands_take_separated_values(self) -> None:
        self.assertEqual(self.run_stdin("focus", "add-site", "--", "youtube.com")[0], 0)
        self.assertEqual(self.run_stdin("focus", "disable-site", "--", "youtube.com")[0], 0)
        self.assertIn(("youtube.com", False, "user"), self.focus.list_sites())
        self.assertEqual(
            self.run_stdin("focus", "edit-site", "--new-domain=youtu.be", "--", "youtube.com")[0], 0
        )
        self.assertEqual(self.run_stdin("focus", "remove-site", "--", "youtu.be")[0], 0)
        self.assertNotIn("youtu.be", [domain for domain, _, _ in self.focus.list_sites()])

    def test_failures_exit_nonzero_with_a_reason(self) -> None:
        code, _, err = self.run_stdin("adjust", "5")
        self.assertEqual(code, 1)
        self.assertIn("No session", err)
        code, _, err = self.run_stdin("settings", "set", "pomodoro_work_minutes", "721")
        self.assertEqual(code, 1)
        self.assertIn("between", err)

    def test_rejects_anything_but_an_array_of_strings(self) -> None:
        for stdin in ("not json\n", '{"a": 1}\n', "[1, 2]\n"):
            with self.subTest(stdin=stdin):
                code, _, err = self.run_cli(cli.ARGS_FROM_STDIN, stdin=stdin)
                self.assertNotEqual(code, 0)
                self.assertIn(cli.ARGS_FROM_STDIN, err)

    def test_no_arguments_and_old_names_open_the_panel(self) -> None:
        with (
            patch("omarchy_focus.cli.shutil.which", return_value="/usr/bin/omarchy-shell"),
            patch("omarchy_focus.cli.subprocess.run") as run,
        ):
            run.return_value.returncode = 0
            for args in ([], ["panel"], ["tui"], ["raise"]):
                with self.subTest(args=args):
                    self.assertEqual(cli.main(args), 0)
        run.assert_called_with(["omarchy-shell", "omarchy-focus", "open"], check=False, capture_output=True)

    def test_widget_never_puts_values_on_a_command_line(self) -> None:
        source = (widget.WIDGET_SOURCE / "BarWidget.qml").read_text(encoding="utf-8")
        self.assertIn('root.argv(["--args-from-stdin"])', source)
        self.assertEqual(source.count("root.argv("), 2)  # status --json, and the action above
        self.assertIn('root.argv(["status", "--json"])', source)


class WidgetFilesTest(unittest.TestCase):
    def test_install_copies_every_page_and_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            plugin = root / "plugins" / widget.WIDGET_ID
            plugin.mkdir(parents=True)
            (plugin / "OldPage.qml").write_text("stale", encoding="utf-8")
            with (
                patch.object(widget, "OMARCHY_DIR", root),
                patch.object(widget, "PLUGIN_DIR", plugin),
                patch.object(widget, "SHELL_CONFIG", root / "shell.json"),
                patch.object(widget, "_shell"),
            ):
                widget.install_widget(place=False)
            installed = {str(path.relative_to(plugin)) for path in plugin.rglob("*") if path.is_file()}
        expected = {str(path.relative_to(widget.WIDGET_SOURCE)) for path in widget.widget_files()}
        self.assertEqual(installed, expected)
        self.assertLessEqual({"BarWidget.qml", "FocusPanel.qml", "TasksPage.qml", "i18n/tr.json"}, installed)

    def test_every_sibling_type_ships(self) -> None:
        names = {path.stem for path in widget.WIDGET_SOURCE.glob("*.qml")}
        for path in widget.WIDGET_SOURCE.glob("*.qml"):
            used = set(re.findall(r"^\s*([A-Z][A-Za-z]+) \{", path.read_text(encoding="utf-8"), flags=re.M))
            # Only types that aren't Qt's or the shell's: those are imported.
            unknown = used - names - KNOWN_TYPES
            self.assertEqual(unknown, set(), path.name)


KNOWN_TYPES = {
    "BarWidget", "Canvas", "Column", "Connections", "FileView", "Flickable", "HoverHandler", "Item", "KeyboardPanel",
    "Loader", "MouseArea", "NumberAnimation", "OpticalGlyph", "PanelKeyCatcher", "Process", "Rectangle", "Repeater", "Row",
    "ShellIpc", "StdioCollector", "Text", "Tile", "Timer", "WidgetButton", "Behavior",
}  # fmt: skip


class CatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = widget.WIDGET_SOURCE / "i18n"
        self.en = json.loads((self.catalog / "en.json").read_text(encoding="utf-8"))
        self.tr = json.loads((self.catalog / "tr.json").read_text(encoding="utf-8"))

    def test_turkish_covers_english(self) -> None:
        self.assertEqual(set(self.en) - set(self.tr), set())
        self.assertEqual(set(self.tr) - set(self.en), set())

    def test_placeholders_match(self) -> None:
        def holes(value: object) -> set[str]:
            text = value if isinstance(value, str) else json.dumps(value)
            return set(re.findall(r"%\d", text))

        for key, value in self.en.items():
            self.assertEqual(holes(value), holes(self.tr[key]), key)

    def test_every_key_in_the_code_exists(self) -> None:
        used: set[str] = set()
        for path in widget.WIDGET_SOURCE.glob("*.qml"):
            used |= set(re.findall(r"""\btn?\("([a-zA-Z.]+)"\s*[,)]""", path.read_text(encoding="utf-8")))
        model = (widget.WIDGET_SOURCE / "Model.js").read_text(encoding="utf-8")
        used |= set(re.findall(r'"(phase\.[a-zA-Z]+)"', model))
        self.assertGreater(len(used), 50)
        self.assertEqual(used - set(self.en), set())
        # Keys built at runtime: "tab." + name, "tasks.filter." + key and so on.
        dynamic = (
            "tab.",
            "priority.",
            "tasks.filter.",
            "tasks.sort.",
            "tasks.empty.",
            "due.",
            "editor.inWeek",
        )
        unused = {key for key in set(self.en) - used if not key.startswith(dynamic)}
        self.assertEqual(unused, set())
