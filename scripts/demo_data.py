#!/usr/bin/env python3
"""Seed a throwaway Omarchy Focus database with realistic demo history.

Used for screenshots and manual testing without touching real data:

    XDG_DATA_HOME=/tmp/of-demo python scripts/demo_data.py
    XDG_DATA_HOME=/tmp/of-demo omarchy-focus stats
"""

from __future__ import annotations

import json
import os
import random
import sys
from datetime import timedelta
from pathlib import Path

if "XDG_DATA_HOME" not in os.environ:
    sys.exit("Refusing to run without XDG_DATA_HOME pointing at a scratch directory.")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omarchy_focus.bootstrap import build_services  # noqa: E402
from omarchy_focus.paths import DB_PATH  # noqa: E402
from omarchy_focus.utils import local_now, to_iso  # noqa: E402

TASKS = [
    ("Ship v0.2 release notes", "high", "release", 50, "in_progress"),
    ("Review Hyprland keybind PR", "high", "review", 25, "pending"),
    ("Refactor stats queries", "medium", "code", 100, "pending"),
    ("Write Omarchy plugin docs", "medium", "docs", 50, "pending"),
    ("Clean up dotfiles", "low", "chores", 25, "pending"),
    ("Record demo GIF", "medium", "release", 25, "done"),
    ("Fix long-break cadence", "high", "code", 50, "done"),
]


def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    random.seed(7)
    services = build_services()
    services.settings.set("notifications_enabled", False)
    task_ids = []
    for title, priority, tag, estimate, status in TASKS:
        task = services.tasks.add_task(title, priority=priority, tags=tag, estimated_minutes=estimate)
        if status != "pending":
            services.tasks.update_task(task.id, status=status)
        task_ids.append(task.id)

    now = local_now()
    rows = []
    for days_ago in range(118, -1, -1):
        day = (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)
        weekend = day.weekday() >= 5
        # Ramp up over time, lighter weekends, a few days off.
        base = 1 + int(4 * (118 - days_ago) / 118)
        count = 0 if random.random() < (0.45 if weekend else 0.12) else max(0, base + random.randint(-1, 2))
        if days_ago == 0:
            count = 3
        clock = day.replace(hour=random.choice([8, 9, 10]), minute=random.choice([0, 15, 30]))
        for _ in range(count):
            if clock.hour == 12:
                clock += timedelta(hours=1)
            minutes = random.choice([50, 50, 50, 25])
            interrupted = random.random() < 0.12
            seconds = minutes * 60 if not interrupted else random.randint(5, minutes - 5) * 60
            if clock + timedelta(seconds=seconds) > now:
                break
            rows.append(
                (
                    random.choice(task_ids[:5]),
                    to_iso(clock),
                    to_iso(clock + timedelta(seconds=seconds)),
                    seconds,
                    0 if interrupted else 1,
                    1 if interrupted else 0,
                )
            )
            clock += timedelta(seconds=seconds, minutes=10)
    with services.db.connection() as conn:
        conn.executemany(
            """
            INSERT INTO pomodoro_sessions (
                task_id, session_type, state, started_at, ended_at,
                duration_seconds, completed, interrupted, notes
            ) VALUES (?, 'work', 'running', ?, ?, ?, ?, ?, 'demo')
            """,
            rows,
        )
        sites = ["reddit.com", "youtube.com", "x.com", "news.ycombinator.com", "instagram.com"]
        for index in range(9):
            started = now - timedelta(days=index % 6, hours=2 + index)
            conn.execute(
                """
                INSERT INTO focus_sessions (session_id, started_at, ends_at, ended_actual_at, active,
                    blocked_sites_json, notes)
                VALUES (?, ?, ?, ?, 0, ?, 'demo')
                """,
                (
                    f"demo{index}",
                    to_iso(started),
                    to_iso(started + timedelta(minutes=50)),
                    to_iso(started + timedelta(minutes=50)),
                    json.dumps(sites[: 2 + index % 4]),
                ),
            )
        for domain in ("youtube.com", "x.com", "news.ycombinator.com"):
            conn.execute(
                "INSERT OR IGNORE INTO blocked_sites (domain, enabled, created_at, source) VALUES (?, 1, ?, 'user')",
                (domain, to_iso(now)),
            )
    print(f"Seeded {len(rows)} sessions into {DB_PATH}")


if __name__ == "__main__":
    main()
