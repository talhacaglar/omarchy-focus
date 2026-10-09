"""General helpers."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

from .paths import APP_NAME, APP_SLUG, CHANGE_STAMP_PATH, RUNTIME_DIR, WAYBAR_SIGNAL

TUI_LOCK_PATH = RUNTIME_DIR / f"{APP_SLUG}.lock"
TUI_WINDOW_PATH = RUNTIME_DIR / f"{APP_SLUG}.window.json"


def utc_now() -> datetime:
    return datetime.now(UTC)


def current_boot_id() -> str | None:
    boot_id_path = Path("/proc/sys/kernel/random/boot_id")
    try:
        value = boot_id_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def local_now() -> datetime:
    return utc_now().astimezone()


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    # Persisted timestamps are always UTC ISO strings, but guard against
    # legacy / hand-edited rows that may be naive to avoid aware/naive
    # subtraction crashes in remaining_seconds()/elapsed_seconds().
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def parse_user_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    formats = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%d.%m.%Y",
        "%d.%m.%Y %H:%M",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.astimezone() if parsed.tzinfo else parsed.replace(tzinfo=local_now().tzinfo)
        except ValueError:
            continue
    raise ValueError(f"Unsupported datetime format: {value}")


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone().strftime("%d %b %Y %H:%M")


def format_date(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone().strftime("%d %b")


def seconds_to_clock(total_seconds: int) -> str:
    total_seconds = max(0, int(total_seconds))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def minutes_to_label(minutes: int | None) -> str:
    if not minutes:
        return "—"
    hours, rem = divmod(minutes, 60)
    if hours:
        return f"{hours}h {rem}m" if rem else f"{hours}h"
    return f"{rem}m"


def progress_bar(value: int, maximum: int, width: int = 16) -> str:
    if maximum <= 0:
        return "░" * width
    ratio = max(0.0, min(1.0, value / maximum))
    filled = round(ratio * width)
    return "█" * filled + "░" * (width - filled)


def sparkline(values: list[int]) -> str:
    if not values:
        return "▁"
    blocks = "▁▂▃▄▅▆▇█"
    top = max(values)
    if top <= 0:
        return blocks[0] * len(values)
    return "".join(blocks[min(len(blocks) - 1, round((value / top) * (len(blocks) - 1)))] for value in values)


def coerce_tags(raw: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if raw is None:
        return []
    source = raw if isinstance(raw, (list, tuple)) else re.split(r"[, ]+", raw.strip())
    return sorted({tag.strip().lstrip("#").lower() for tag in source if tag and tag.strip()})


def json_dumps(value: Any) -> str:
    def default_serializer(obj: Any) -> str:
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=default_serializer)


def poke_status_bar() -> None:
    """Tell status bars that state changed.

    The Omarchy Shell widget watches the change stamp with inotify; Waybar
    listens for its realtime signal.
    """
    with contextlib.suppress(OSError):
        CHANGE_STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHANGE_STAMP_PATH.write_text(f"{utc_now().timestamp():.3f}\n", encoding="utf-8")
    subprocess.run(["pkill", f"-RTMIN+{WAYBAR_SIGNAL}", "waybar"], check=False, capture_output=True)


# Compatibility for third-party code that imported the old helper.
poke_waybar = poke_status_bar


def acquire_tui_lock() -> TextIO | None:
    TUI_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = TUI_LOCK_PATH.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


def _discover_tui_window_address() -> str | None:
    if not shutil.which("hyprctl"):
        return None
    result = subprocess.run(["hyprctl", "clients", "-j"], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        clients = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    parent_pid = os.getppid()
    for client in clients:
        if int(client.get("pid", -1)) == parent_pid:
            address = str(client.get("address") or "").strip()
            if address:
                return address

    for client in clients:
        classes = " ".join(
            str(client.get(key) or "") for key in ("class", "initialClass", "title", "initialTitle")
        ).lower()
        if APP_SLUG in classes:
            address = str(client.get("address") or "").strip()
            if address:
                return address
    return None


def register_tui_window() -> None:
    address = _discover_tui_window_address()
    if not address:
        return
    TUI_WINDOW_PATH.parent.mkdir(parents=True, exist_ok=True)
    TUI_WINDOW_PATH.write_text(
        json.dumps(
            {
                "address": address,
                "pid": os.getpid(),
                "parent_pid": os.getppid(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def clear_tui_window_state() -> None:
    with contextlib.suppress(FileNotFoundError):
        TUI_WINDOW_PATH.unlink()


def focus_existing_tui() -> bool:
    if not shutil.which("hyprctl"):
        return False

    address = None
    if TUI_WINDOW_PATH.exists():
        try:
            payload = json.loads(TUI_WINDOW_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        recorded_pid = int(payload.get("pid", 0) or 0)
        if recorded_pid and not Path(f"/proc/{recorded_pid}").exists():
            clear_tui_window_state()
        else:
            address = str(payload.get("address") or "").strip() or None

    if not address:
        address = _discover_tui_window_address()
    if not address:
        return False

    result = subprocess.run(
        ["hyprctl", "dispatch", "focuswindow", f"address:{address}"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def focus_app_tui() -> None:
    if focus_existing_tui():
        return

    launcher = shutil.which("omarchy-launch-or-focus-tui")
    if launcher:
        subprocess.Popen(
            [launcher, APP_SLUG, "tui"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return

    terminal = shutil.which("xdg-terminal-exec")
    app = shutil.which(APP_SLUG)
    if terminal and app:
        subprocess.Popen(
            [terminal, "-e", app, "tui"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def play_alert_sound() -> None:
    canberra = shutil.which("canberra-gtk-play")
    if canberra:
        subprocess.Popen(
            [canberra, "-i", "bell", "-d", APP_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return

    paplay = shutil.which("paplay")
    if paplay:
        for sample in (
            Path("/usr/share/sounds/freedesktop/stereo/bell.oga"),
            Path("/usr/share/sounds/freedesktop/stereo/complete.oga"),
        ):
            if sample.exists():
                subprocess.Popen(
                    [paplay, str(sample)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return

    try:
        sys.stdout.write("\a")
        sys.stdout.flush()
    except Exception:
        pass


def elapsed_seconds(start: datetime | None, end: datetime | None = None) -> int:
    if start is None:
        return 0
    end = end or utc_now()
    return max(0, int((end - start).total_seconds()))


def remaining_seconds(end: datetime | None, now: datetime | None = None) -> int:
    if end is None:
        return 0
    now = now or utc_now()
    return max(0, int((end - now).total_seconds()))


def start_of_day(value: datetime | None = None) -> datetime:
    value = value or local_now()
    local = value.astimezone()
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def start_of_week(value: datetime | None = None) -> datetime:
    day = start_of_day(value)
    return day - timedelta(days=day.weekday())
