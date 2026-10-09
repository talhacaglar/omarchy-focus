"""Application settings."""

from __future__ import annotations

import json
from typing import Any

from .database import Database

DEFAULT_SETTINGS: dict[str, Any] = {
    "pomodoro_work_minutes": 50,
    "pomodoro_short_break_minutes": 10,
    "pomodoro_long_break_minutes": 25,
    "pomodoro_long_break_every": 4,
    "default_view": "dashboard",
    "theme_variant": "midnight-gold",
    "notifications_enabled": True,
    "bar_output_mode": "json",
    "strict_mode_default": False,
    "focus_auto_release": True,
    "focus_on_pomodoro_start": False,
    "daily_goal_minutes": 150,
    # Raise the TUI when a work session ends. Off by default: the bar widget,
    # notification and sound already announce the break.
    "open_app_on_complete": False,
}


class SettingsService:
    def __init__(self, db: Database) -> None:
        self.db = db
        stored = {
            row["key"]: row["value_json"] for row in self.db.fetchall("SELECT key, value_json FROM settings")
        }
        if "waybar_output_mode" in stored:
            if "bar_output_mode" not in stored:
                self.db.set_setting("bar_output_mode", stored["waybar_output_mode"])
                stored["bar_output_mode"] = stored["waybar_output_mode"]
            self.db.execute("DELETE FROM settings WHERE key = 'waybar_output_mode'")
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
        self.db.set_setting(key, json.dumps(value))

    def update_many(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            self.set(key, value)
