"""Task data must stay private to its owner (0.2.4).

Covers the gaps found after 0.2.3: the legacy ``clar-focus`` copy left
readable after migration, task titles exposed through ``notify-send``'s
process arguments, and runtime files placed in a guessable ``/tmp`` path.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

from omarchy_focus import notifications, paths
from omarchy_focus.database import Database
from omarchy_focus.services.tasks import TaskService

SECRET = "Secret plan for Q4"


def mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


@contextlib.contextmanager
def umask(value: int) -> Iterator[None]:
    old = os.umask(value)
    try:
        yield
    finally:
        os.umask(old)


@contextlib.contextmanager
def app_roots(root: Path) -> Iterator[None]:
    """Point every path in ``paths`` at XDG-style roots under ``root``."""
    roots = {name: root / name for name in ("config", "data", "state", "cache")}
    slug = paths.APP_SLUG
    with (
        patch.object(paths, "_CONFIG_ROOT", roots["config"]),
        patch.object(paths, "_DATA_ROOT", roots["data"]),
        patch.object(paths, "_STATE_ROOT", roots["state"]),
        patch.object(paths, "_CACHE_ROOT", roots["cache"]),
        patch.object(paths, "CONFIG_DIR", roots["config"] / slug),
        patch.object(paths, "DATA_DIR", roots["data"] / slug),
        patch.object(paths, "STATE_DIR", roots["state"] / slug),
        patch.object(paths, "CACHE_DIR", roots["cache"] / slug),
        patch.object(paths, "DB_PATH", roots["data"] / slug / paths.DB_NAME),
    ):
        yield


def make_loose_legacy(root: Path) -> tuple[Path, sqlite3.Connection]:
    """A pre-0.2.3 ``clar-focus`` install: 0755 directories, 0644 database.

    The returned connection is left open so the WAL and shm files exist, as
    they do while the bar widget or TUI is running.
    """
    legacy_data = root / "data" / "clar-focus"
    legacy_config = root / "config" / "clar-focus"
    for directory in (legacy_data, legacy_config, root / "state" / "clar-focus"):
        directory.mkdir(parents=True)
        directory.chmod(0o755)
    (legacy_config / "settings.json").write_text("{}", encoding="utf-8")
    db = Database(legacy_data / "focus.db")
    db.initialize()
    TaskService(db).add_task(SECRET)
    conn = sqlite3.connect(db.path)
    conn.execute("SELECT count(*) FROM tasks").fetchone()  # opens the WAL
    for suffix in ("", "-wal", "-shm"):
        (legacy_data / f"focus.db{suffix}").chmod(0o644)
    return legacy_data, conn


class LegacyDataPrivacyTest(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.root = Path(tmpdir.name)
        self.legacy, conn = make_loose_legacy(self.root)
        self.addCleanup(conn.close)

    def assert_legacy_private(self) -> None:
        for directory in ("data", "config", "state"):
            self.assertEqual(mode(self.root / directory / "clar-focus"), 0o700, directory)
        for suffix in ("", "-wal", "-shm"):
            self.assertEqual(mode(self.legacy / f"focus.db{suffix}"), 0o600, suffix or "db")

    def test_first_migration_tightens_the_legacy_copy(self) -> None:
        with umask(0o022), app_roots(self.root):
            paths.ensure_app_dirs()
            migrated = paths.DB_PATH
        self.assert_legacy_private()
        with contextlib.closing(sqlite3.connect(migrated)) as conn:
            self.assertEqual(conn.execute("SELECT title FROM tasks").fetchone()[0], SECRET)
        # The old copy is kept (a downgrade still finds its data), only locked down.
        self.assertTrue((self.legacy / "focus.db").exists())

    def test_install_migrated_by_an_earlier_release_is_tightened(self) -> None:
        # 0.2.0-0.2.3 already copied the data, so migration returns early;
        # the legacy copy must be secured anyway.
        new_db = self.root / "data" / paths.APP_SLUG / paths.DB_NAME
        new_db.parent.mkdir(parents=True)
        sqlite3.connect(new_db).close()
        with umask(0o022), app_roots(self.root):
            paths.ensure_app_dirs()
        self.assert_legacy_private()

    def test_migrated_config_directory_stays_private(self) -> None:
        # shutil.copytree copies the source directory's 0755 mode onto the target.
        with umask(0o022), app_roots(self.root):
            paths.ensure_app_dirs()
            config_dir = paths.CONFIG_DIR
        self.assertEqual(mode(config_dir), 0o700)
        self.assertEqual(mode(config_dir / "settings.json"), 0o600)

    def test_symlinked_legacy_directory_is_not_followed(self) -> None:
        outside = self.root / "outside"
        outside.mkdir(mode=0o755)
        outside.chmod(0o755)
        link = self.root / "cache" / "clar-focus"
        link.parent.mkdir(parents=True)
        link.symlink_to(outside)
        with app_roots(self.root):
            paths.ensure_app_dirs()
        self.assertEqual(mode(outside), 0o755)


class NotificationPrivacyTest(unittest.TestCase):
    def test_body_goes_over_dbus_not_process_arguments(self) -> None:
        with (
            patch.object(notifications, "_send_dbus", return_value=True) as dbus,
            patch.object(notifications.subprocess, "run") as run,
        ):
            notifications.notify("Pomodoro started", SECRET)
        dbus.assert_called_once()
        self.assertIn(SECRET, dbus.call_args.args)
        run.assert_not_called()

    def test_fallback_never_puts_the_body_in_argv(self) -> None:
        with (
            patch.object(notifications, "_send_dbus", return_value=False),
            patch.object(notifications.shutil, "which", return_value="/usr/bin/notify-send"),
            patch.object(notifications.subprocess, "run") as run,
        ):
            notifications.notify("Task complete", SECRET, urgency="critical")
        argv = run.call_args.args[0]
        self.assertIn("Task complete", argv)
        self.assertNotIn(SECRET, " ".join(argv))

    def test_disabled_notifications_send_nothing(self) -> None:
        with (
            patch.object(notifications, "_send_dbus") as dbus,
            patch.object(notifications.subprocess, "run") as run,
        ):
            notifications.notify("Task complete", SECRET, enabled=False)
        dbus.assert_not_called()
        run.assert_not_called()

    def test_dbus_failure_is_not_fatal(self) -> None:
        with patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent/bus"}):
            self.assertFalse(notifications._send_dbus("t", "b", "normal"))


class RuntimeDirTest(unittest.TestCase):
    def test_session_runtime_dir_is_used_when_set(self) -> None:
        self.assertEqual(
            paths.resolve_runtime_dir({"XDG_RUNTIME_DIR": "/run/user/1000"}, fallback=Path("/x")),
            Path("/run/user/1000"),
        )

    def test_missing_runtime_dir_never_falls_back_to_shared_tmp(self) -> None:
        # /tmp/<uid> can be created first by another user, who then controls
        # the lock and stamp files (symlinks to the victim's files).
        with tempfile.TemporaryDirectory() as tmpdir:
            fallback = Path(tmpdir) / "run"
            with patch.object(paths, "_SYSTEMD_RUNTIME", Path(tmpdir) / "missing"):
                resolved = paths.resolve_runtime_dir({}, fallback=fallback)
            self.assertEqual(resolved, fallback)
            self.assertNotEqual(resolved, Path(f"/tmp/{os.getuid()}"))

    def test_private_runtime_dir_we_own_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run = Path(tmpdir) / "1000"
            run.mkdir(mode=0o700)
            with patch.object(paths, "_SYSTEMD_RUNTIME", run):
                self.assertEqual(paths.resolve_runtime_dir({}, fallback=Path("/fallback")), run)

    def test_runtime_dir_owned_by_someone_else_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run = Path(tmpdir) / "1000"
            run.mkdir(mode=0o700)
            with (
                patch.object(paths, "_SYSTEMD_RUNTIME", run),
                patch.object(paths.os, "getuid", return_value=os.getuid() + 1),
            ):
                resolved = paths.resolve_runtime_dir({}, fallback=Path("/fallback"))
        self.assertEqual(resolved, Path("/fallback"))

    def test_runtime_dir_others_can_enter_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run = Path(tmpdir) / "1000"
            run.mkdir()
            run.chmod(0o755)
            with patch.object(paths, "_SYSTEMD_RUNTIME", run):
                self.assertEqual(paths.resolve_runtime_dir({}, fallback=Path("/fallback")), Path("/fallback"))


FAKE_NOTIFY_SEND = textwrap.dedent(
    """\
    #!/bin/sh
    printf '%s\\n' "$*" >> "$NOTIFY_LOG"
    """
)


class EndToEndPrivacyTest(unittest.TestCase):
    """Run the real CLI as a user with umask 022 and a readable legacy install."""

    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.root = Path(tmpdir.name)
        _, conn = make_loose_legacy(self.root)
        conn.close()
        for suffix in ("", "-wal", "-shm"):
            with contextlib.suppress(FileNotFoundError):
                (self.root / "data" / "clar-focus" / f"focus.db{suffix}").chmod(0o644)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        for name in ("notify-send", "pkill", "hyprctl", "canberra-gtk-play"):
            shim = bin_dir / name
            shim.write_text(FAKE_NOTIFY_SEND if name == "notify-send" else "#!/bin/sh\n", encoding="utf-8")
            shim.chmod(0o755)
        self.log = self.root / "notify.log"
        self.env = {
            "HOME": str(self.root / "home"),
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "XDG_RUNTIME_DIR": str(self.root / "runtime"),
            # No session bus: forces the notify-send fallback, the risky path.
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent/bus",
            "NOTIFY_LOG": str(self.log),
        }
        (self.root / "runtime").mkdir(mode=0o700)

    def cli(self, *args: str) -> str:
        result = subprocess.run(
            [sys.executable, "-m", "omarchy_focus", *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            preexec_fn=lambda: os.umask(0o022),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_task_titles_stay_private(self) -> None:
        # The title on add-task's own command line is the user's choice; what
        # matters is that the app never republishes it.
        self.cli("add-task", SECRET)
        self.cli("start", "--task-id", "1")
        self.cli("tasks", "done", "1")
        self.cli("status", "--json")

        notified = self.log.read_text(encoding="utf-8")
        self.assertIn("Pomodoro started", notified)
        self.assertIn("Task complete", notified)
        self.assertNotIn(SECRET, notified)

        exposed = [
            f"{oct(mode(path))} {path.relative_to(self.root)}"
            for top in ("config", "data", "state", "cache")
            for path in (self.root / top).rglob("*")
            if readable_by_others(path, self.root / top)
        ]
        # Unlike the XDG roots above, the runtime dir itself must be private.
        exposed += [
            f"{oct(mode(path))} {path.relative_to(self.root)}"
            for path in [self.root / "runtime", *(self.root / "runtime").rglob("*")]
            if readable_by_others(path, self.root)
        ]
        self.assertEqual(exposed, [])


def readable_by_others(path: Path, top: Path) -> bool:
    """Whether a group member or other user can read ``path``.

    ``top`` (an XDG root) is assumed traversable, as ~/.local/share is.
    Every directory between it and ``path`` must be traversable too.
    """
    if path.is_symlink():
        return False
    parent = path.parent
    while parent != top:
        if not mode(parent) & 0o011:
            return False
        parent = parent.parent
    return bool(mode(path) & 0o044)


if __name__ == "__main__":
    unittest.main()
