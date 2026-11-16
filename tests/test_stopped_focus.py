"""A work session stopped after five minutes still counts as focus time."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from omarchy_focus.utils import local_now, to_iso, utc_now
from test_v02 import ServicesTestCase


class StoppedSessionFocusTest(ServicesTestCase):
    def run_for(self, minutes: float, *, paused: float = 0) -> None:
        """Start a 25-minute session that has been going for `minutes`, then stop it."""
        self.pomodoro.start(minutes=25, auto_focus=False)
        raw = self.pomodoro._load_raw()
        assert raw is not None
        raw["started_at"] = to_iso(utc_now() - timedelta(minutes=minutes + paused))
        raw["paused_seconds"] = int(paused * 60)
        self.pomodoro._save_raw(raw)
        self.pomodoro.stop()

    def test_a_stopped_session_past_five_minutes_adds_what_it_ran(self) -> None:
        self.run_for(12)
        stats = self.stats.snapshot()
        self.assertEqual(stats.today_focus_minutes, 12)
        self.assertEqual(stats.week_focus_minutes, 12)
        self.assertEqual(stats.today_completed_pomodoros, 0)
        self.assertEqual(stats.interrupted_sessions_week, 1)
        self.assertEqual(self.stats.daily_minutes(1)[-1][1], 12)
        self.assertEqual(sum(self.stats.hourly_minutes()), 12)
        self.assertEqual(stats.top_task_focus, [("Unassigned", 12)])
        self.assertEqual(stats.focus_days[-1][1], 12)
        self.assertEqual(stats.streak_days, 1)

    def test_pauses_are_not_focus_time(self) -> None:
        self.run_for(8, paused=30)
        self.assertEqual(self.stats.snapshot().today_focus_minutes, 8)

    def test_under_five_minutes_is_a_false_start(self) -> None:
        self.run_for(4.9)
        stats = self.stats.snapshot()
        self.assertEqual(stats.today_focus_minutes, 0)
        self.assertEqual(stats.streak_days, 0)

    def test_it_adds_to_finished_sessions(self) -> None:
        self.pomodoro.start(minutes=25, auto_focus=False)
        raw = self.pomodoro._load_raw()
        assert raw is not None
        raw["started_at"] = to_iso(utc_now() - timedelta(minutes=25, seconds=1))
        self.pomodoro._save_raw(raw)
        self.finish_current_session()
        self.pomodoro.skip_break()
        self.run_for(10)
        stats = self.stats.snapshot()
        self.assertEqual(stats.today_focus_minutes, 35)
        self.assertEqual(stats.today_completed_pomodoros, 1)

    def test_breaks_never_count(self) -> None:
        self.pomodoro.start_break(minutes=15)
        raw = self.pomodoro._load_raw()
        assert raw is not None
        raw["started_at"] = to_iso(utc_now() - timedelta(minutes=10))
        self.pomodoro._save_raw(raw)
        self.pomodoro.stop()
        self.assertEqual(self.stats.snapshot().today_focus_minutes, 0)

    def test_a_session_lost_to_a_reboot_does_not_count(self) -> None:
        # Its length runs to the next boot, not to when the machine went down.
        start = local_now().replace(hour=0, minute=1)
        with patch("omarchy_focus.services.pomodoro.current_boot_id", return_value="boot-a"):
            self.pomodoro.start(minutes=25, auto_focus=False)
        raw = self.pomodoro._load_raw()
        assert raw is not None
        raw["started_at"] = to_iso(start)
        self.pomodoro._save_raw(raw)
        with patch("omarchy_focus.services.pomodoro.current_boot_id", return_value="boot-b"):
            self.pomodoro.tick()
        self.assertEqual(self.stats.snapshot().today_focus_minutes, 0)
