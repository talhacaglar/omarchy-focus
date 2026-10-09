"""Filesystem paths used by Omarchy Focus."""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
from pathlib import Path

APP_NAME = "Omarchy Focus"
APP_SLUG = "omarchy-focus"
# Names this project shipped under before. Data is migrated from the first
# one that exists so upgrades keep tasks, history and settings.
LEGACY_APP_SLUGS = ("clar-focus",)

HOME = Path.home()
_CONFIG_ROOT = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
_DATA_ROOT = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local" / "share"))
_STATE_ROOT = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local" / "state"))
_CACHE_ROOT = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache"))
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/tmp/{os.getuid()}"))

CONFIG_DIR = _CONFIG_ROOT / APP_SLUG
DATA_DIR = _DATA_ROOT / APP_SLUG
STATE_DIR = _STATE_ROOT / APP_SLUG
CACHE_DIR = _CACHE_ROOT / APP_SLUG

DB_NAME = "focus.db"
DB_PATH = DATA_DIR / DB_NAME
# Touched after every state change. The Omarchy Shell widget watches it with
# inotify, so the bar updates instantly without polling the CLI.
CHANGE_STAMP_PATH = RUNTIME_DIR / f"{APP_SLUG}.changed"
WAYBAR_SIGNAL = 12


def _copy_database(source: Path, target: Path) -> None:
    """Copy a live SQLite database, including WAL contents, atomically."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".migrating")
    partial.unlink(missing_ok=True)
    with (
        contextlib.closing(sqlite3.connect(source)) as src,
        contextlib.closing(sqlite3.connect(partial)) as dst,
    ):
        src.backup(dst)
    os.replace(partial, target)


def migrate_legacy_data() -> None:
    """Bring data over from a previous app name, leaving the old copy intact.

    Only the database and config are migrated. The legacy data directory may
    also hold the installer's virtualenv, which must not move underneath a
    running interpreter, so it is copied file-by-file instead of moved.
    """
    if DB_PATH.exists():
        return
    for slug in LEGACY_APP_SLUGS:
        legacy_db = _DATA_ROOT / slug / DB_NAME
        if not legacy_db.exists():
            continue
        _copy_database(legacy_db, DB_PATH)
        legacy_config = _CONFIG_ROOT / slug
        if legacy_config.is_dir() and not (CONFIG_DIR.exists() and any(CONFIG_DIR.iterdir())):
            shutil.copytree(legacy_config, CONFIG_DIR, symlinks=True, dirs_exist_ok=True)
        return


def ensure_app_dirs() -> None:
    """Create app directories if they do not exist."""
    migrate_legacy_data()
    for path in (CONFIG_DIR, DATA_DIR, STATE_DIR, CACHE_DIR):
        path.mkdir(parents=True, exist_ok=True)
