"""Desktop bar status helpers.

The JSON shape is understood by Omarchy Shell's native ``command`` widget.
It also remains compatible with Waybar's custom module format.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from . import __version__
from .bootstrap import ServiceContainer
from .charts import peak_window
from .focus_hosts_helper import SYSTEM_HELPER_PATH
from .models import SessionPhase, SessionType, Task
from .paths import APP_NAME, CHANGE_STAMP_PATH
from .services.pomodoro import session_elapsed_seconds
from .utils import local_now, poke_status_bar, progress_bar, remaining_seconds, seconds_to_clock

# Bumped when the JSON consumed by the Omarchy Shell widget changes shape.
STATE_SCHEMA = 2


def _ms(value: datetime | None) -> int | None:
    return int(value.timestamp() * 1000) if value else None


def _task_payload(task: Task, focus_minutes: dict[int, int]) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "priority": task.priority.value,
        "status": task.status.value,
        "tags": list(task.tags),
        "estimate": task.estimated_minutes,
        # In the local form `tasks edit --due` accepts, for the panel's editor.
        "due": task.due_at.astimezone().strftime("%Y-%m-%d %H:%M") if task.due_at else None,
        "due_at_ms": _ms(task.due_at),
        "focus_minutes": focus_minutes.get(task.id, 0),
    }


def build_state_payload(services: ServiceContainer, *, heatmap_days: int = 84) -> dict[str, Any]:
    """Everything the bar panel needs in one call (`status --json`).

    Timestamps are epoch milliseconds so QML can count down locally between
    refreshes. Older keys from earlier releases are kept for scripts.
    """
    if not CHANGE_STAMP_PATH.exists():
        # The shell widget can only inotify-watch a file that exists.
        poke_status_bar()
    services.sync()
    pomodoro = services.pomodoro.snapshot()
    pending_break = services.pomodoro.pending_break()
    focus = services.focus.snapshot()
    stats = services.stats.snapshot()
    settings = services.settings
    goal = int(settings.get("daily_goal_minutes") or 0)
    finished = stats.completed_sessions_week
    attempted = finished + stats.interrupted_sessions_week
    hours = services.stats.hourly_minutes(days=30)
    peak = peak_window(hours)
    focus_minutes = services.stats.focus_minutes_by_task()
    return {
        "schema": STATE_SCHEMA,
        "version": __version__,
        "generated_at_ms": _ms(local_now()),
        "pending_tasks": services.tasks.count_pending(),
        "pomodoro": {
            "phase": pomodoro.phase.value,
            "type": pomodoro.session_type.value if pomodoro.session_type else None,
            "remaining_seconds": pomodoro.remaining_seconds,
            "total_seconds": pomodoro.total_seconds,
            "ends_at_ms": _ms(pomodoro.ends_at),
            "task_id": pomodoro.task_id,
            "task_title": pomodoro.task_title,
            "cycle": pomodoro.cycle_count,
            "auto_focus": pomodoro.auto_focus,
            "strict_focus": pomodoro.strict_focus,
            # A session with no timer counts up: elapsed is
            # now - started_at_ms - paused_seconds while it runs.
            "open_ended": pomodoro.open_ended,
            "started_at_ms": _ms(pomodoro.started_at),
            "paused_seconds": pomodoro.paused_seconds,
            "elapsed_seconds": session_elapsed_seconds(pomodoro) if pomodoro.started_at else 0,
        },
        "pending_break": pending_break,
        "focus": {
            "active": focus.active,
            "strict": focus.strict_mode,
            "sites": list(focus.blocked_sites),
            "ends_at": focus.ends_at.isoformat() if focus.ends_at else None,
            "ends_at_ms": _ms(focus.ends_at),
            "started_at_ms": _ms(focus.started_at),
            "consistent": focus.system_consistent,
        },
        "stats": {
            "today_pomodoros": stats.today_completed_pomodoros,
            "today_focus_minutes": stats.today_focus_minutes,
            "today_tasks_done": stats.completed_tasks_today,
            "goal_minutes": goal,
            "week_focus_minutes": stats.week_focus_minutes,
            "streak_days": stats.streak_days,
            "completion_rate": round(finished / attempted, 3) if attempted else None,
            "week": [{"label": label, "minutes": minutes} for label, minutes in stats.focus_days],
            "week_tasks_done": stats.completed_tasks_week,
            "week_sessions_finished": finished,
            "week_sessions_cut": stats.interrupted_sessions_week,
            "week_guard_sessions": stats.focus_sessions_week,
            "top_tasks": [{"title": title, "minutes": minutes} for title, minutes in stats.top_task_focus],
            "blocked_sites": [{"domain": site, "sessions": count} for site, count in stats.blocked_sites],
            "hours": hours,
            "peak_start": peak[0] if peak else None,
        },
        "heatmap": [
            {"date": day, "minutes": minutes} for day, minutes in services.stats.daily_minutes(heatmap_days)
        ],
        "next_tasks": [
            {
                "id": task.id,
                "title": task.title,
                "priority": task.priority.value,
                "status": task.status.value,
                "estimate": task.estimated_minutes,
            }
            for task in services.tasks.list_open(limit=5)
        ],
        "tasks": [_task_payload(task, focus_minutes) for task in services.tasks.list_for_panel()],
        "sites": [
            {"domain": domain, "enabled": enabled, "source": source}
            for domain, enabled, source in services.focus.list_sites()
        ],
        "settings": {
            "work_minutes": int(settings.get("pomodoro_work_minutes")),
            "short_break_minutes": int(settings.get("pomodoro_short_break_minutes")),
            "long_break_minutes": int(settings.get("pomodoro_long_break_minutes")),
            "long_break_every": int(settings.get("pomodoro_long_break_every")),
            "daily_goal_minutes": goal,
            "guard_minutes": int(settings.get("guard_minutes")),
            "notifications_enabled": bool(settings.get("notifications_enabled")),
            "focus_on_pomodoro_start": bool(settings.get("focus_on_pomodoro_start")),
            "strict_mode_default": bool(settings.get("strict_mode_default")),
            "focus_auto_release": bool(settings.get("focus_auto_release")),
        },
        # False means every change to an active guard asks for a password.
        "passwordless_guard": os.access(SYSTEM_HELPER_PATH, os.X_OK),
    }


def build_bar_payload(services: ServiceContainer) -> dict[str, Any]:
    services.sync()
    pomodoro = services.pomodoro.snapshot()
    pending_break = services.pomodoro.pending_break()
    focus = services.focus.snapshot()
    stats = services.stats.snapshot()
    pending = services.tasks.count_pending()

    if pomodoro.open_ended and pomodoro.phase in {SessionPhase.RUNNING, SessionPhase.PAUSED}:
        elapsed = seconds_to_clock(session_elapsed_seconds(pomodoro))
        paused = pomodoro.phase == SessionPhase.PAUSED
        text = f"{'󰏤' if paused else '󰄉'} {elapsed}"
        if pomodoro.task_title and not paused:
            text += f" · {pomodoro.task_title[:20]}"
        tooltip = "\n".join(
            [
                "Focus, no timer (paused)" if paused else "Focus, no timer",
                f"Elapsed: {elapsed}",
                f"Task: {pomodoro.task_title or 'Unassigned'}",
                f"Pending tasks: {pending}",
            ]
        )
        return {"text": text, "tooltip": tooltip, "class": ["active", "paused" if paused else "pomodoro"]}

    if pomodoro.phase == SessionPhase.RUNNING and pomodoro.session_type == SessionType.WORK:
        icon = "󰄉"
        text = f"{icon} {seconds_to_clock(pomodoro.remaining_seconds)}"
        if pomodoro.task_title:
            text += f" · {pomodoro.task_title[:20]}"
        tooltip = "\n".join(
            [
                "Focus Session",
                f"Time left: {seconds_to_clock(pomodoro.remaining_seconds)}",
                f"Task: {pomodoro.task_title or 'Unassigned'}",
                f"Pending tasks: {pending}",
                f"Today: {stats.today_completed_pomodoros} pomodoros · {stats.today_focus_minutes}m",
            ]
        )
        return {"text": text, "tooltip": tooltip, "class": ["active", "pomodoro"]}

    if pomodoro.phase == SessionPhase.RUNNING and pomodoro.session_type in {
        SessionType.SHORT_BREAK,
        SessionType.LONG_BREAK,
    }:
        label = "Long Break" if pomodoro.session_type == SessionType.LONG_BREAK else "Break"
        return {
            "text": f"󰁅 {seconds_to_clock(pomodoro.remaining_seconds)}",
            "tooltip": f"{label}\nTime left: {seconds_to_clock(pomodoro.remaining_seconds)}",
            "class": ["active", "break"],
        }

    if pomodoro.phase == SessionPhase.PAUSED:
        return {
            "text": f"󰏤 {seconds_to_clock(pomodoro.remaining_seconds)}",
            "tooltip": f"Paused session\nResume from: {pomodoro.task_title or 'Unassigned'}",
            "class": ["active", "paused"],
        }

    if pending_break:
        raw_minutes = pending_break.get("minutes", 10)
        minutes = int(raw_minutes) if isinstance(raw_minutes, int | str) else 10
        task_title = str(pending_break.get("task_title") or "") or "Unassigned"
        return {
            "text": f"󰁅 {minutes}m?",
            "tooltip": "\n".join(
                [
                    "Pomodoro Complete",
                    f"Break ready: {minutes} minute(s)",
                    f"Task: {task_title}",
                    "Click to start the break.",
                ]
            ),
            "class": ["active", "break"],
        }

    if focus.active:
        strict = " · strict" if focus.strict_mode else ""
        blocked_preview = ", ".join(list(focus.blocked_sites)[:3])
        time_left = seconds_to_clock(remaining_seconds(focus.ends_at)) if focus.ends_at else None
        text = f"󰈈 {time_left}" if time_left else f"󰈈 Focus{strict}"
        tooltip = "\n".join(
            [
                "Focus Mode",
                f"Time left: {time_left or 'manual'}",
                f"Blocked: {len(focus.blocked_sites)} site(s)",
                blocked_preview or "Custom site list is empty",
                f"Pending tasks: {pending}",
            ]
        )
        return {"text": text, "tooltip": tooltip, "class": ["active", "focus"]}

    next_task = services.tasks.get_next_focus_candidate()
    task_label = next_task.title if next_task else "Idle"
    goal = int(services.settings.get("daily_goal_minutes") or 0) or 150
    goal_progress = progress_bar(stats.today_focus_minutes, goal, width=10)
    tooltip = "\n".join(
        [
            APP_NAME,
            f"Next task: {task_label}",
            f"Pending tasks: {pending}",
            f"Today: {stats.today_completed_pomodoros} pomodoros · {stats.today_focus_minutes}m",
            f"Goal: {goal_progress} {stats.today_focus_minutes}/{goal}m",
            f"Week: {stats.week_focus_minutes}m · {stats.streak_days}d streak",
        ]
    )
    return {"text": f" {pending}", "tooltip": tooltip, "class": ""}


def render_bar(services: ServiceContainer, *, json_mode: bool = True) -> str:
    payload = build_bar_payload(services)
    if json_mode:
        return json.dumps(payload, ensure_ascii=False)
    return str(payload["text"])
