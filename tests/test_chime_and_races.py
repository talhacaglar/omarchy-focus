"""The end-of-session chime, and the fixes found while testing it: a session
that several processes finish at once, a task deleted under a running session,
and values the CLI used to let through."""

from __future__ import annotations

import io
import subprocess
import unittest
from contextlib import redirect_stderr
from datetime import timedelta
from unittest.mock import patch

from omarchy_focus import utils
from omarchy_focus.cli import main
from omarchy_focus.exceptions import FocusModeError, PomodoroError, TaskNotFoundError
from omarchy_focus.focus_hosts_helper import HostsStatus
from omarchy_focus.models import SessionPhase
from omarchy_focus.services.focus import FocusService
from omarchy_focus.settings import DEFAULT_SETTINGS
from omarchy_focus.utils import utc_now
from test_v02 import ServicesTestCase


class ChimeTest(ServicesTestCase):
    def test_every_chime_ships_as_an_ogg_file(self) -> None:
        for name in utils.CHIMES:
            with self.subTest(name=name):
                self.assertEqual(utils.chime_path(name).read_bytes()[:4], b"OggS")

    def test_plays_the_bundled_file_and_never_the_system_bell(self) -> None:
        with (
            patch.object(utils.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}"),
            patch.object(utils.subprocess, "Popen") as popen,
        ):
            self.assertTrue(utils.play_chime("session-end"))
        command = popen.call_args.args[0]
        self.assertEqual(command, ["/usr/bin/pw-play", str(utils.chime_path("session-end"))])
        self.assertNotIn("bell", " ".join(command))

    def test_falls_back_through_the_players_then_gives_up_quietly(self) -> None:
        with (
            patch.object(
                utils.shutil, "which", side_effect=lambda name: "/usr/bin/x" if "canberra" in name else None
            ),
            patch.object(utils.subprocess, "Popen") as popen,
        ):
            self.assertTrue(utils.play_chime("break-end"))
        self.assertEqual(popen.call_args.args[0][-2:], ["-f", str(utils.chime_path("break-end"))])
        with patch.object(utils.shutil, "which", return_value=None):
            self.assertFalse(utils.play_chime())
        with self.assertRaises(ValueError):
            utils.play_chime("airhorn")

    def test_a_session_and_a_break_each_ring_their_own_chime(self) -> None:
        with patch("omarchy_focus.services.pomodoro.play_chime") as chime:
            self.pomodoro.start(minutes=25, auto_focus=False)
            self.finish_current_session()
            self.pomodoro.start_break()
            self.finish_current_session()
        self.assertEqual([call.args[0] for call in chime.call_args_list], ["session-end", "break-end"])

    def test_the_sound_can_be_switched_off(self) -> None:
        self.assertIs(DEFAULT_SETTINGS["sound_enabled"], True)
        self.settings.set("sound_enabled", False)
        with patch("omarchy_focus.services.pomodoro.play_chime") as chime:
            self.pomodoro.start(minutes=25, auto_focus=False)
            self.finish_current_session()
        chime.assert_not_called()

    def test_sound_command_plays_without_a_database(self) -> None:
        with (
            patch("omarchy_focus.cli.play_chime", return_value=True) as chime,
            patch("omarchy_focus.cli.build_services") as build,
        ):
            self.assertEqual(main(["sound", "break-end"]), 0)
        chime.assert_called_once_with("break-end")
        build.assert_not_called()
        with patch("omarchy_focus.cli.play_chime", return_value=False), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["sound"]), 1)


class FinishOnceTest(ServicesTestCase):
    def sessions(self) -> list[tuple[int, str]]:
        rows = self.db.fetchall("SELECT completed, notes FROM pomodoro_sessions ORDER BY id")
        return [(row["completed"], row["notes"]) for row in rows]

    def test_a_session_others_already_finished_is_not_recorded_again(self) -> None:
        """The bar, the heartbeat and a CLI call can all tick on the second it ends."""
        self.pomodoro.start(minutes=25, auto_focus=False)
        raw = self.pomodoro._load_raw()
        assert raw is not None
        raw["ends_at"] = "2000-01-01T00:00:00+00:00"
        self.pomodoro._save_raw(raw)
        # Every later reader still holds the state the first one is finishing.
        with (
            patch.object(self.pomodoro, "_load_raw", return_value=dict(raw)),
            patch("omarchy_focus.services.pomodoro.play_chime") as chime,
        ):
            for _ in range(4):
                self.pomodoro.tick()
        self.assertEqual(self.sessions(), [(1, "work complete")])
        chime.assert_called_once_with("session-end")

    def test_stopping_what_just_ran_out_keeps_it_finished(self) -> None:
        self.pomodoro.start(minutes=25, auto_focus=False)
        stale = self.pomodoro._load_raw()
        self.finish_current_session()
        with patch.object(self.pomodoro, "_load_raw", return_value=stale):
            self.assertEqual(self.pomodoro.stop().phase, SessionPhase.IDLE)
        self.assertEqual(self.sessions(), [(1, "work complete")])

    def test_concurrent_processes_record_one_session(self) -> None:
        """The real thing: a dozen `status` calls on a session that just ran out."""
        import os
        import sys
        from pathlib import Path

        root = Path(self.tmpdir.name)
        env = {
            **os.environ,
            "PATH": str(root / "nobin"),  # no player, no notify-send, no pkill
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent",
            **{f"XDG_{name}_HOME": str(root / name.lower()) for name in ("CONFIG", "DATA", "STATE", "CACHE")},
            "XDG_RUNTIME_DIR": str(root / "run"),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        }
        (root / "nobin").mkdir()
        (root / "run").mkdir(mode=0o700)
        cli = [sys.executable, "-m", "omarchy_focus"]
        script = (
            "import json, sqlite3, sys\n"
            "c = sqlite3.connect(sys.argv[1])\n"
            "key = 'pomodoro.current'\n"
            "v = json.loads(c.execute('SELECT value_json FROM app_state WHERE key=?', (key,)).fetchone()[0])\n"
            "v['ends_at'] = '2000-01-01T00:00:00+00:00'\n"
            "c.execute('UPDATE app_state SET value_json=? WHERE key=?', (json.dumps(v), key)); c.commit()\n"
        )
        database = root / "data" / "omarchy-focus" / "focus.db"
        subprocess.run(
            [*cli, "settings", "set", "notifications_enabled", "false"],
            env=env,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [*cli, "start", "--minutes", "25", "--no-focus"], env=env, check=True, capture_output=True
        )
        subprocess.run([sys.executable, "-c", script, str(database)], check=True)
        racers = [
            subprocess.Popen([*cli, "status"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            for _ in range(12)
        ]
        errors = [racer.communicate()[1] for racer in racers]
        self.assertEqual([error for error in errors if error], [])
        import sqlite3

        with sqlite3.connect(database) as conn:
            count = conn.execute("SELECT COUNT(*) FROM pomodoro_sessions WHERE completed = 1").fetchone()[0]
        self.assertEqual(count, 1)


class DeletedTaskTest(ServicesTestCase):
    def test_a_session_outlives_its_task(self) -> None:
        """The foreign key refused the record, so the session could never be stopped."""
        task = self.tasks.add_task("Short-lived")
        self.pomodoro.start(task_id=task.id, minutes=25, auto_focus=False)
        self.tasks.delete_task(task.id)
        self.assertEqual(self.pomodoro.stop().phase, SessionPhase.IDLE)
        row = self.db.fetchone("SELECT task_id, interrupted FROM pomodoro_sessions")
        self.assertIsNone(row["task_id"])
        self.assertEqual(row["interrupted"], 1)

    def test_it_can_also_run_out_and_earn_its_break(self) -> None:
        task = self.tasks.add_task("Short-lived")
        self.pomodoro.start(task_id=task.id, minutes=25, auto_focus=False)
        self.tasks.delete_task(task.id)
        self.finish_current_session()
        self.pomodoro.start_break()
        self.finish_current_session()
        rows = self.db.fetchall("SELECT task_id, completed FROM pomodoro_sessions")
        self.assertEqual([(row["task_id"], row["completed"]) for row in rows], [(None, 1), (None, 1)])


class RejectedValuesTest(ServicesTestCase):
    def test_a_missing_task_does_not_cost_the_running_session(self) -> None:
        self.pomodoro.start(minutes=25, auto_focus=False)
        with self.assertRaises(TaskNotFoundError):
            self.pomodoro.start(task_id=999, minutes=25, auto_focus=False)
        self.assertEqual(self.pomodoro.snapshot().phase, SessionPhase.RUNNING)
        self.assertIsNone(self.db.fetchone("SELECT 1 FROM pomodoro_sessions"))

    def test_session_and_break_lengths_have_limits(self) -> None:
        with self.assertRaises(PomodoroError):
            self.pomodoro.start(minutes=721, auto_focus=False)
        self.pomodoro.start(minutes=720, auto_focus=False)
        self.pomodoro.stop()
        for minutes in (-5, 241):
            with self.subTest(minutes=minutes), self.assertRaises(PomodoroError):
                self.pomodoro.start_break(minutes=minutes)
        self.assertEqual(self.pomodoro.snapshot().phase, SessionPhase.IDLE)

    def test_an_estimate_is_above_zero(self) -> None:
        with self.assertRaises(ValueError):
            self.tasks.add_task("Negative", estimated_minutes=-5)
        task = self.tasks.add_task("Fine", estimated_minutes=30)
        with self.assertRaises(ValueError):
            self.tasks.update_task(task.id, estimated_minutes=0)
        self.assertEqual(self.tasks.get_task(task.id).estimated_minutes, 30)

    def test_tasks_list_refuses_an_unknown_sort(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["tasks", "list", "--sort", "bogus"])


if __name__ == "__main__":
    unittest.main()


class ExpiredGuardTest(ServicesTestCase):
    """A guard that ran out but needs root to come down, on a machine where
    sudo wants a password: every bar refresh used to run two refused sudos."""

    def expired_guard(self) -> None:
        from omarchy_focus.models import FocusStateSnapshot
        from omarchy_focus.utils import utc_now

        self.focus._persist_snapshot(
            FocusStateSnapshot(
                active=True,
                session_id="guard1",
                blocked_sites=("reddit.com",),
                started_at=utc_now() - timedelta(hours=2),
                ends_at=utc_now() - timedelta(hours=1),
            )
        )

    def test_a_refused_release_is_not_retried_on_every_refresh(self) -> None:
        self.expired_guard()
        with (
            patch("omarchy_focus.services.focus.inspect_hosts_file", return_value=HostsStatus(active=True)),
            patch.object(
                self.focus, "_run_helper", side_effect=FocusModeError("a password is required")
            ) as helper,
        ):
            for _ in range(5):
                self.assertTrue(self.focus.status().active)
            self.assertEqual(helper.call_count, 1)
            # Ten minutes on, it gets another go.
            later = utc_now() + FocusService.RELEASE_RETRY_AFTER + timedelta(seconds=1)
            with patch("omarchy_focus.services.focus.utc_now", return_value=later):
                self.focus.status()
            self.assertEqual(helper.call_count, 2)

    def test_turning_it_off_by_hand_still_works_and_clears_the_wait(self) -> None:
        self.expired_guard()
        with patch("omarchy_focus.services.focus.inspect_hosts_file", return_value=HostsStatus(active=True)):
            with patch.object(self.focus, "_run_helper", side_effect=FocusModeError("no")):
                self.focus.status()
            with (
                patch.object(self.focus, "_run_helper", return_value=HostsStatus(active=False)),
                patch("omarchy_focus.services.focus.notify"),
                patch("omarchy_focus.services.focus.poke_status_bar"),
            ):
                self.assertFalse(self.focus.stop().active)
        self.assertIsNone(self.db.get_state(FocusService.RELEASE_FAILED_KEY))

    def test_a_background_release_runs_sudo_once_without_a_probe(self) -> None:
        with (
            patch("omarchy_focus.services.focus.os.geteuid", return_value=1000),
            patch("omarchy_focus.services.focus.shutil.which", return_value="/usr/bin/sudo"),
            patch("omarchy_focus.services.focus.subprocess.run") as run,
        ):
            self.assertEqual(self.focus._privilege_prefix(["helper"], interactive=False), ["sudo", "-n"])
        run.assert_not_called()
