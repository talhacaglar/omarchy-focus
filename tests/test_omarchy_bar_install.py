from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from omarchy_focus.widget import update_shell_config, write_atomic

MODULE = {"id": "omarchy-focus"}
LEGACY = {
    "id": "clarfocus",
    "type": "command",
    "exec": "~/.local/bin/clar-focus-bar status",
    "interval": 2,
}


def shell(center: list[dict], **sections: list[dict]) -> dict:
    layout = {"left": [{"id": "clar.workspaces"}], "center": center, "right": [{"id": "omarchy.tray"}]}
    layout.update(sections)
    return {"version": 1, "bar": {"position": "top", "layout": layout}}


class OmarchyBarInstallTest(unittest.TestCase):
    def test_replaces_legacy_command_widget_in_place(self) -> None:
        config = shell([{"id": "omarchy.indicators"}, LEGACY, {"id": "omarchy.system-update"}])
        self.assertTrue(update_shell_config(config, MODULE))
        ids = [item["id"] for item in config["bar"]["layout"]["center"]]
        self.assertEqual(ids, ["omarchy.indicators", "omarchy-focus", "omarchy.system-update"])
        self.assertEqual(config["bar"]["position"], "top")
        self.assertEqual(config["bar"]["layout"]["left"], [{"id": "clar.workspaces"}])
        self.assertFalse(update_shell_config(config, MODULE))

    def test_keeps_existing_native_entry_and_its_settings(self) -> None:
        native = {"id": "omarchy-focus", "showIdleCount": False}
        config = shell([{"id": "omarchy.clock"}], right=[native, {"id": "omarchy.tray"}])
        self.assertFalse(update_shell_config(config, MODULE))
        self.assertEqual(config["bar"]["layout"]["right"][0], native)

    def test_removes_duplicate_legacy_entries(self) -> None:
        legacy_exec = {"id": "custom", "type": "command", "exec": "~/.local/bin/omarchy-focus-bar status"}
        config = shell([LEGACY, {"id": "omarchy.clock"}], right=[legacy_exec, {"id": "omarchy.tray"}])
        self.assertTrue(update_shell_config(config, MODULE))
        self.assertEqual(
            [item["id"] for item in config["bar"]["layout"]["center"]], ["omarchy-focus", "omarchy.clock"]
        )
        self.assertEqual(config["bar"]["layout"]["right"], [{"id": "omarchy.tray"}])

    def test_inserts_after_clock_and_writes_valid_json(self) -> None:
        config = shell([{"id": "omarchy.indicators"}, {"id": "omarchy.clock"}])
        self.assertTrue(update_shell_config(config, MODULE))
        ids = [item["id"] for item in config["bar"]["layout"]["center"]]
        self.assertEqual(ids, ["omarchy.indicators", "omarchy.clock", "omarchy-focus"])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "shell.json"
            write_atomic(path, config)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), config)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
