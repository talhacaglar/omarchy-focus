"""Application settings."""

from __future__ import annotations

import json
from typing import Any

from .database import Database

DEFAULT_SETTINGS: dict[str, Any] = {
    # Also the length last picked in the panel. 0 is a session with no timer
    # that runs until it is stopped.
    "pomodoro_work_minutes": 50,
    "pomodoro_short_break_minutes": 10,
    "pomodoro_long_break_minutes": 25,
    "pomodoro_long_break_every": 4,
    "notifications_enabled": True,
    "strict_mode_default": False,
    "focus_auto_release": True,
    "focus_on_pomodoro_start": False,
    "daily_goal_minutes": 150,
    # Length offered when starting the site guard on its own.
    "guard_minutes": 50,
}

# Settings of the removed terminal app, dropped from existing databases.
RETIRED_SETTINGS = (
    "default_view",
    "theme_variant",
    "bar_output_mode",
    "waybar_output_mode",
    "open_app_on_complete",
)

# Allowed range of each number. 0 turns off the long break and the daily goal,
# and gives a work session no timer.
SETTING_RANGES: dict[str, tuple[int, int]] = {
    "pomodoro_work_minutes": (0, 720),
    "pomodoro_short_break_minutes": (1, 240),
    "pomodoro_long_break_minutes": (1, 240),
    "pomodoro_long_break_every": (0, 24),
    "daily_goal_minutes": (0, 1440),
    "guard_minutes": (1, 720),
}


class SettingsService:
    def __init__(self, db: Database) -> None:
        self.db = db
        stored = {
            row["key"]: row["value_json"] for row in self.db.fetchall("SELECT key, value_json FROM settings")
        }
        for key in RETIRED_SETTINGS:
            if key in stored:
                self.db.execute("DELETE FROM settings WHERE key = ?", (key,))
        # Only write when a default is actually missing; the common case is a
        # read-only startup.
        missing = {key: value for key, value in DEFAULT_SETTINGS.items() if key not in stored}
        if missing:
            self.db.seed_defaults(missing)

    def get(self, key: str, default: Any = None) -> Any:
        row = self.db.fetchone("SELECT value_json FROM settings WHERE key = ?", (key,))
        if not row:
            return DEFAULT_SETTINGS.get(key, default)
        return json.loads(row["value_json"])

    def all(self) -> dict[str, Any]:
        rows = self.db.fetchall("SELECT key, value_json FROM settings ORDER BY key")
        values = dict(DEFAULT_SETTINGS)
        values.update({row["key"]: json.loads(row["value_json"]) for row in rows})
        return values

    def set(self, key: str, value: Any) -> None:
        self.db.set_setting(key, json.dumps(self._validated(key, value)))

    @staticmethod
    def _validated(key: str, value: Any) -> Any:
        if key not in DEFAULT_SETTINGS:
            raise ValueError(f"Unknown setting: {key}")
        expected = type(DEFAULT_SETTINGS[key])
        if type(value) is not expected:
            raise ValueError(f"{key} must be a {'whole number' if expected is int else expected.__name__}")
        if key in SETTING_RANGES:
            low, high = SETTING_RANGES[key]
            if not low <= value <= high:
                raise ValueError(f"{key} must be between {low} and {high}")
        return value

    def update_many(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            self.set(key, value)
