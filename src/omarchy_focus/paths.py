"""Filesystem paths used by Omarchy Focus."""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import stat
from collections.abc import Mapping
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

CONFIG_DIR = _CONFIG_ROOT / APP_SLUG
DATA_DIR = _DATA_ROOT / APP_SLUG
STATE_DIR = _STATE_ROOT / APP_SLUG
CACHE_DIR = _CACHE_ROOT / APP_SLUG

_SYSTEMD_RUNTIME = Path("/run/user") / str(os.getuid())


def _owned_private_dir(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077


def resolve_runtime_dir(env: Mapping[str, str], *, fallback: Path) -> Path:
    """Where the change stamp, TUI lock and window files live.

    Without ``XDG_RUNTIME_DIR`` (cron, su, ssh without pam_systemd) the old
    ``/tmp/<uid>`` fallback was guessable: another user could create it first
    and plant symlinks, so the lock's truncate or the stamp write would hit
    the victim's files. Only a directory we own and nobody else can enter is
    accepted; otherwise the files go in a private cache subdirectory.
    """
    if env.get("XDG_RUNTIME_DIR"):
        return Path(env["XDG_RUNTIME_DIR"])
    if _owned_private_dir(_SYSTEMD_RUNTIME):
        return _SYSTEMD_RUNTIME
    return fallback


RUNTIME_DIR = resolve_runtime_dir(os.environ, fallback=CACHE_DIR / "run")

DB_NAME = "focus.db"
DB_PATH = DATA_DIR / DB_NAME
# Touched after every state change. The Omarchy Shell widget watches it with
# inotify, so the bar updates instantly without polling the CLI.
CHANGE_STAMP_PATH = RUNTIME_DIR / f"{APP_SLUG}.changed"
WAYBAR_SIGNAL = 12


PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def private_dir(path: Path) -> None:
    """Create ``path`` readable only by the current user, fixing older installs.

    Tasks, notes and history live under these directories, so other local
    users must not be able to list or read them whatever the umask is.
    """
    path.mkdir(mode=PRIVATE_DIR_MODE, parents=True, exist_ok=True)
    if path.stat().st_mode & 0o777 != PRIVATE_DIR_MODE:
        path.chmod(PRIVATE_DIR_MODE)


def _copy_database(source: Path, target: Path) -> None:
    """Copy a live SQLite database, including WAL contents, atomically."""
    private_dir(target.parent)
    partial = target.with_name(target.name + ".migrating")
    partial.unlink(missing_ok=True)
    with (
        contextlib.closing(sqlite3.connect(source)) as src,
        contextlib.closing(sqlite3.connect(partial)) as dst,
    ):
        src.backup(dst)
    partial.chmod(PRIVATE_FILE_MODE)
    os.replace(partial, target)


def migrate_legacy_data() -> None:
    """Bring data over from a previous app name, leaving the old copy in place.

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
            # copytree copies the legacy modes, including CONFIG_DIR's own.
            _tighten_tree(CONFIG_DIR)
        return


def _tighten(path: Path, mode: int) -> None:
    """chmod ``path`` unless it is a symlink, missing, or not ours to change."""
    with contextlib.suppress(OSError):
        info = path.lstat()
        if not stat.S_ISLNK(info.st_mode) and stat.S_IMODE(info.st_mode) != mode:
            path.chmod(mode)


def _tighten_tree(root: Path) -> None:
    _tighten(root, PRIVATE_DIR_MODE)
    for parent, dirs, files in os.walk(root):
        for name in dirs:
            _tighten(Path(parent) / name, PRIVATE_DIR_MODE)
        for name in files:
            _tighten(Path(parent) / name, PRIVATE_FILE_MODE)


def secure_legacy_data() -> None:
    """Lock down what earlier releases left under their old names.

    The legacy copy is kept so a downgrade still finds its data, but it holds
    the same tasks as the new database and was created with the umask (often
    0755/0644). Installs migrated by 0.2.0-0.2.3 are covered too, which is why
    this runs on every start rather than only during migration.
    """
    for slug in LEGACY_APP_SLUGS:
        for root in (_CONFIG_ROOT, _DATA_ROOT, _STATE_ROOT, _CACHE_ROOT):
            if (root / slug).is_dir():
                _tighten(root / slug, PRIVATE_DIR_MODE)
        for suffix in ("", "-wal", "-shm", "-journal"):
            _tighten(_DATA_ROOT / slug / f"{DB_NAME}{suffix}", PRIVATE_FILE_MODE)


def ensure_app_dirs() -> None:
    """Create app directories if they do not exist."""
    for path in (CONFIG_DIR, DATA_DIR, STATE_DIR, CACHE_DIR):
        private_dir(path)
    migrate_legacy_data()
    secure_legacy_data()
