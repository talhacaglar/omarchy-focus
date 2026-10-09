"""Install the native Omarchy Shell bar widget for the current user.

The widget's QML ships inside this package (``shell_widget/``) so every
install method (install.sh, pip, the AUR package) can place it with
``omarchy-focus widget install``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

WIDGET_ID = "omarchy-focus"
WIDGET_SOURCE = Path(__file__).with_name("shell_widget")
WIDGET_FILES = ("manifest.json", "BarWidget.qml", "FocusPanel.qml", "Model.js")
OMARCHY_DIR = Path.home() / ".config" / "omarchy"
PLUGIN_DIR = OMARCHY_DIR / "plugins" / WIDGET_ID
SHELL_CONFIG = OMARCHY_DIR / "shell.json"

SECTIONS = ("left", "center", "right")
LEGACY_IDS = {"clarfocus", "omarchy-focus-command"}
LEGACY_EXEC_MARKERS = ("clar-focus-bar", "omarchy-focus-bar", "clar-focus-waybar")


def is_legacy_entry(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("id") in LEGACY_IDS:
        return True
    command = str(item.get("exec") or "")
    return any(marker in command for marker in LEGACY_EXEC_MARKERS)


def _layout(config: dict[str, Any]) -> dict[str, list[Any]]:
    bar = config.setdefault("bar", {})
    if not isinstance(bar, dict):
        raise ValueError("shell.json: 'bar' must be an object")
    layout = bar.setdefault("layout", {})
    if not isinstance(layout, dict):
        raise ValueError("shell.json: 'bar.layout' must be an object")
    for section in SECTIONS:
        if not isinstance(layout.setdefault(section, []), list):
            raise ValueError(f"shell.json: 'bar.layout.{section}' must be a list")
    return layout


def _default_slot(layout: dict[str, list[Any]]) -> tuple[str, int]:
    """Right after the clock, else before the indicators, else at the end."""
    center = layout["center"]
    ids = [item.get("id") if isinstance(item, dict) else None for item in center]
    if "omarchy.clock" in ids:
        return "center", ids.index("omarchy.clock") + 1
    if "omarchy.indicators" in ids:
        return "center", ids.index("omarchy.indicators")
    return "center", len(center)


def update_shell_config(config: dict[str, Any], module: dict[str, Any]) -> bool:
    """Return True when the layout changed."""
    layout = _layout(config)
    has_native = any(
        isinstance(item, dict) and item.get("id") == module.get("id")
        for section in SECTIONS
        for item in layout[section]
    )
    first_legacy: tuple[str, int] | None = None
    removed = False
    for section in SECTIONS:
        kept: list[Any] = []
        for item in layout[section]:
            if is_legacy_entry(item):
                if first_legacy is None:
                    first_legacy = (section, len(kept))
                removed = True
                continue
            kept.append(item)
        layout[section][:] = kept
    if has_native:
        return removed
    section, index = first_legacy or _default_slot(layout)
    layout[section].insert(index, dict(module))
    return True


def write_atomic(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _shell(*args: str) -> None:
    if shutil.which("omarchy-shell"):
        subprocess.run(["omarchy-shell", "-q", *args], check=False, capture_output=True)


def install_widget(*, place: bool = True) -> list[str]:
    """Copy the widget into ~/.config/omarchy/plugins and add it to the bar."""
    if not OMARCHY_DIR.is_dir():
        raise RuntimeError("~/.config/omarchy not found; the widget needs Omarchy Shell")
    messages = []
    upgrade = PLUGIN_DIR.exists()
    PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
    for stale in PLUGIN_DIR.glob("*"):
        if stale.is_file() and stale.suffix in {".qml", ".js", ".json"}:
            stale.unlink()
    for name in WIDGET_FILES:
        shutil.copyfile(WIDGET_SOURCE / name, PLUGIN_DIR / name)
    _shell("shell", "rescanPlugins")
    messages.append(("Upgraded" if upgrade else "Installed") + f" widget in {PLUGIN_DIR}")
    if place:
        config = (
            json.loads(SHELL_CONFIG.read_text(encoding="utf-8")) if SHELL_CONFIG.exists() else {"version": 1}
        )
        if update_shell_config(config, {"id": WIDGET_ID}):
            if SHELL_CONFIG.exists():
                backup = SHELL_CONFIG.with_name(f"shell.json.bak-{WIDGET_ID}-{datetime.now():%Y%m%d-%H%M%S}")
                shutil.copy2(SHELL_CONFIG, backup)
                messages.append(f"Added to the bar next to the clock (backup: {backup.name})")
            write_atomic(SHELL_CONFIG, config)
        else:
            messages.append("Already in the bar layout")
    if upgrade:
        messages.append("If the popup looks stale, run: omarchy restart shell")
    return messages


def remove_widget() -> list[str]:
    messages = []
    if SHELL_CONFIG.exists():
        config = json.loads(SHELL_CONFIG.read_text(encoding="utf-8"))
        layout = _layout(config)
        before = sum(len(layout[s]) for s in SECTIONS)
        for section in SECTIONS:
            layout[section][:] = [
                item
                for item in layout[section]
                if not (isinstance(item, dict) and item.get("id") == WIDGET_ID) and not is_legacy_entry(item)
            ]
        if sum(len(layout[s]) for s in SECTIONS) != before:
            write_atomic(SHELL_CONFIG, config)
            messages.append("Removed from the bar layout")
    if PLUGIN_DIR.exists():
        shutil.rmtree(PLUGIN_DIR)
        messages.append(f"Deleted {PLUGIN_DIR}")
    _shell("shell", "rescanPlugins")
    return messages or ["Widget was not installed"]
