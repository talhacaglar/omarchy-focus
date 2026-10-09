"""SQLite persistence layer."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .paths import DB_PATH
from .utils import json_dumps, to_iso, utc_now

DEFAULT_BLOCKED_SITES = (
    "reddit.com",
    "www.reddit.com",
    "old.reddit.com",
    "instagram.com",
    "www.instagram.com",
)

# Bump this whenever a migration step is added below. The value is stored in
# SQLite's PRAGMA user_version so existing databases can evolve without data
# loss.
SCHEMA_VERSION = 1


class Database:
    """Thin SQLite wrapper with migrations."""

    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path

    def initialize(self) -> None:
        with self.connection() as conn:
            current = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if current >= SCHEMA_VERSION:
                # Fast path: every CLI call and bar refresh lands here, so an
                # up-to-date database skips the DDL (and its write lock).
                return
            conn.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    priority TEXT NOT NULL DEFAULT 'medium',
                    status TEXT NOT NULL DEFAULT 'pending',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    estimated_minutes INTEGER,
                    due_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    archived_at TEXT
                );

                CREATE TABLE IF NOT EXISTS pomodoro_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                    session_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_seconds INTEGER NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 0,
                    interrupted INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS focus_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    strict_mode INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    ends_at TEXT,
                    ended_actual_at TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    blocked_sites_json TEXT NOT NULL,
                    auto_release INTEGER NOT NULL DEFAULT 1,
                    recovered INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS blocked_sites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user'
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_tasks_completed_at ON tasks(completed_at);
                CREATE INDEX IF NOT EXISTS idx_tasks_due_at ON tasks(due_at);
                CREATE INDEX IF NOT EXISTS idx_pomodoro_lookup
                    ON pomodoro_sessions(session_type, completed, started_at);
                CREATE INDEX IF NOT EXISTS idx_pomodoro_task ON pomodoro_sessions(task_id);
                CREATE INDEX IF NOT EXISTS idx_focus_active ON focus_sessions(active);
                CREATE INDEX IF NOT EXISTS idx_focus_started ON focus_sessions(started_at);
                """
            )
            if current == 0:
                # Seed once. Re-seeding on every start would resurrect default
                # sites the user deliberately removed.
                created_at = to_iso(utc_now())
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO blocked_sites (domain, enabled, created_at, source)
                    VALUES (?, 1, ?, 'default')
                    """,
                    [(domain, created_at) for domain in DEFAULT_BLOCKED_SITES],
                )
            self._run_migrations(conn)

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        """Apply incremental schema migrations based on PRAGMA user_version.

        Add a new ``if current < N`` block (and bump ``SCHEMA_VERSION``) for each
        future schema change so existing databases upgrade in place.
        """
        current = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if current >= SCHEMA_VERSION:
            return
        # v0 -> v1: baseline. The CREATE ... IF NOT EXISTS statements above bring
        # legacy databases up to the v1 shape (tables + indexes); nothing extra
        # to do here beyond recording the version.
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        # Per-connection setting: without it ON DELETE SET NULL never fires.
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def fetchone(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        with self.connection() as conn:
            return conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return list(conn.execute(sql, params).fetchall())

    def execute(self, sql: str, params: tuple | list = ()) -> None:
        with self.connection() as conn:
            conn.execute(sql, params)

    def upsert_state(self, key: str, value_json: str) -> None:
        now = to_iso(utc_now())
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO app_state (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, value_json, now),
            )

    def delete_state(self, key: str) -> None:
        self.execute("DELETE FROM app_state WHERE key = ?", (key,))

    def get_state(self, key: str) -> sqlite3.Row | None:
        return self.fetchone("SELECT key, value_json, updated_at FROM app_state WHERE key = ?", (key,))

    def set_setting(self, key: str, value_json: str) -> None:
        now = to_iso(utc_now())
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, value_json, now),
            )

    def seed_defaults(self, defaults: dict[str, object]) -> None:
        with self.connection() as conn:
            for key, value in defaults.items():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO settings (key, value_json, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (key, json_dumps(value), to_iso(utc_now())),
                )
