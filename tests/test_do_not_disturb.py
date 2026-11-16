"""Do-not-disturb for the length of a work session."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from omarchy_focus import notifications
from omarchy_focus.bar import build_state_payload
from omarchy_focus.bootstrap import ServiceContainer
from omarchy_focus.settings import DEFAULT_SETTINGS
from test_v02 import ServicesTestCase

# conftest.py swaps this out for the length of each test.
REAL_ASK = notifications._ask
SILENCE = "omarchy_focus.services.pomodoro.silence_desktop"
UNSILENCE = "omarchy_focus.services.pomodoro.unsilence_desktop"


class SessionSilenceTest(ServicesTestCase):
    def test_a_work_session_silences_the_desktop_until_it_is_stopped(self) -> None:
        self.assertIs(DEFAULT_SETTINGS["silence_notifications"], True)
        with patch(SILENCE, return_value=True) as silence, patch(UNSILENCE) as unsilence:
            self.pomodoro.start(minutes=25, auto_focus=False)
            silence.assert_called_once_with()
            self.assertTrue(self.pomodoro.snapshot().silenced)
            self.pomodoro.pause()
            self.pomodoro.resume()
            unsilence.assert_not_called()
            self.pomodoro.stop()
            unsilence.assert_called_once_with()

    def test_finishing_lifts_it_before_the_completion_notification(self) -> None:
        order: list[str] = []
        with (
            patch(SILENCE, return_value=True),
            patch(UNSILENCE, side_effect=lambda: order.append("unsilence")),
        ):
            self.pomodoro.start(minutes=25, auto_focus=False)
            with patch(
                "omarchy_focus.services.pomodoro.notify",
                side_effect=lambda title, *_, **__: order.append(title),
            ):
                self.finish_current_session()
                # Whoever looks next finds nothing left to lift.
                self.pomodoro.tick()
                self.pomodoro.stop()
        self.assertEqual(order, ["unsilence", "Pomodoro complete"])

    def test_a_do_not_disturb_that_was_already_on_is_left_on(self) -> None:
        with patch(SILENCE, return_value=False), patch(UNSILENCE) as unsilence:
            self.pomodoro.start(minutes=25, auto_focus=False)
            self.assertFalse(self.pomodoro.snapshot().silenced)
            self.pomodoro.stop()
        unsilence.assert_not_called()

    def test_it_can_be_switched_off_and_breaks_are_never_silenced(self) -> None:
        with patch(SILENCE, return_value=True) as silence, patch(UNSILENCE) as unsilence:
            self.pomodoro.start_break(minutes=5)
            self.pomodoro.stop()
            self.settings.set("silence_notifications", False)
            self.pomodoro.start(minutes=25, auto_focus=False)
            self.pomodoro.stop()
        silence.assert_not_called()
        unsilence.assert_not_called()

    def test_a_session_lost_to_a_reboot_lifts_it(self) -> None:
        with patch(SILENCE, return_value=True), patch(UNSILENCE) as unsilence:
            with patch("omarchy_focus.services.pomodoro.current_boot_id", return_value="boot-a"):
                self.pomodoro.start(minutes=25, auto_focus=False)
            with patch("omarchy_focus.services.pomodoro.current_boot_id", return_value="boot-b"):
                self.pomodoro.tick()
        unsilence.assert_called_once_with()

    def test_the_panel_is_told_the_setting(self) -> None:
        container = ServiceContainer(
            self.db, self.settings, self.tasks, self.focus, self.pomodoro, self.stats
        )
        with (
            patch.object(ServiceContainer, "sync", return_value=None),
            patch("omarchy_focus.bar.poke_status_bar"),
        ):
            payload = build_state_payload(container, heatmap_days=14)
        self.assertIs(payload["settings"]["silence_notifications"], True)


class DesktopSwitchTest(ServicesTestCase):
    def answers(self, table: dict[tuple[str, ...], str | None]):
        self.asked: list[tuple[str, ...]] = []

        def ask(command: list[str]) -> str | None:
            self.asked.append(tuple(command))
            return table.get(tuple(command))

        return patch.object(notifications, "_ask", side_effect=ask)

    def test_omarchy_shell_is_turned_on_only_when_it_was_off(self) -> None:
        shell = ("omarchy-shell", "notifications")
        with self.answers({(*shell, "isDnd"): "off", (*shell, "setDnd", "on"): "on"}):
            self.assertTrue(notifications.silence_desktop())
        self.assertIn((*shell, "setDnd", "on"), self.asked)
        with self.answers({(*shell, "isDnd"): "on"}):
            self.assertFalse(notifications.silence_desktop())
        self.assertEqual(self.asked, [(*shell, "isDnd")])
        with self.answers({(*shell, "setDnd", "off"): "off"}):
            notifications.unsilence_desktop()
        self.assertNotIn(("makoctl", "mode"), self.asked)

    def test_mako_is_the_fallback(self) -> None:
        with self.answers({("makoctl", "mode"): "default", ("makoctl", "mode", "-a", "do-not-disturb"): ""}):
            self.assertTrue(notifications.silence_desktop())
        with self.answers({("makoctl", "mode"): "default\ndo-not-disturb"}):
            self.assertFalse(notifications.silence_desktop())
            notifications.unsilence_desktop()
        self.assertEqual(self.asked[-1], ("makoctl", "mode", "-r", "do-not-disturb"))

    def test_no_known_daemon_is_not_an_error(self) -> None:
        with self.answers({}):
            self.assertFalse(notifications.silence_desktop())
            notifications.unsilence_desktop()

    def test_a_missing_failing_or_hanging_command_answers_nothing(self) -> None:
        self.assertIsNone(REAL_ASK(["omarchy-focus-no-such-command"]))
        with patch.object(notifications.shutil, "which", return_value="/usr/bin/x"):
            with patch.object(notifications.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 2)):
                self.assertIsNone(REAL_ASK(["x"]))
            failed = subprocess.CompletedProcess(["x"], 1, stdout="Target not found.\n", stderr="")
            with patch.object(notifications.subprocess, "run", return_value=failed):
                self.assertIsNone(REAL_ASK(["x"]))
            worked = subprocess.CompletedProcess(["x"], 0, stdout="off\n", stderr="")
            with patch.object(notifications.subprocess, "run", return_value=worked):
                self.assertEqual(REAL_ASK(["x"]), "off")
