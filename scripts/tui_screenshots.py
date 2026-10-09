#!/usr/bin/env python3
"""Render README screenshots of the TUI from a demo database.

    XDG_DATA_HOME=/tmp/of-demo python scripts/demo_data.py
    XDG_DATA_HOME=/tmp/of-demo python scripts/tui_screenshots.py screenshots/

Writes dashboard.svg and statistics.svg; convert with rsvg-convert.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

if "XDG_DATA_HOME" not in os.environ:
    sys.exit("Point XDG_DATA_HOME at the demo data directory first.")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omarchy_focus.bootstrap import ServiceContainer  # noqa: E402
from omarchy_focus.tui.app import OmarchyFocusApp  # noqa: E402


async def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (
        patch("omarchy_focus.tui.app.register_tui_window"),
        patch.object(ServiceContainer, "sync", return_value=None),
    ):
        app = OmarchyFocusApp()
        async with app.run_test(size=(150, 46)) as pilot:
            await pilot.pause(0.5)
            app.save_screenshot("dashboard.svg", path=str(out_dir))
            app.show_view("statistics")
            await pilot.pause(0.5)
            app.save_screenshot("statistics.svg", path=str(out_dir))


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots")))
