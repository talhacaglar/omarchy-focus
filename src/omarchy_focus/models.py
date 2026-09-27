"""Domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class TaskPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    ARCHIVED = "archived"


class SessionType(StrEnum):
    WORK = "work"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


class SessionPhase(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"


@dataclass(slots=True)
class Task:
    id: int
    title: str
    description: str = ""
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    tags: tuple[str, ...] = ()
    estimated_minutes: int | None = None
    due_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    archived_at: datetime | None = None


@dataclass(slots=True)
class TaskFilters:
    search: str = ""
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    tag: str | None = None
    today: bool = False
    completed: bool = False
    include_archived: bool = False
    sort_by: str = "updated_desc"


@dataclass(slots=True)
class PomodoroStateSnapshot:
    phase: SessionPhase = SessionPhase.IDLE
    session_type: SessionType | None = None
    started_at: datetime | None = None
    ends_at: datetime | None = None
    paused_at: datetime | None = None
    paused_seconds: int = 0
    boot_id: str | None = None
    remaining_seconds: int = 0
    task_id: int | None = None
    task_title: str | None = None
    cycle_count: int = 0
    auto_focus: bool = False
    strict_focus: bool = False


@dataclass(slots=True)
class FocusStateSnapshot:
    active: bool = False
    session_id: str | None = None
    strict_mode: bool = False
    blocked_sites: tuple[str, ...] = ()
    started_at: datetime | None = None
    ends_at: datetime | None = None
    recovered: bool = False
    system_consistent: bool = True
    auto_release: bool = True


@dataclass(slots=True)
class AppSummary:
    pomodoro: PomodoroStateSnapshot
    focus: FocusStateSnapshot
    pending_tasks: int = 0
    today_done: int = 0
    today_focus_minutes: int = 0
    active_task_title: str | None = None


@dataclass(slots=True)
class StatsSnapshot:
    today_completed_pomodoros: int = 0
    today_focus_minutes: int = 0
    week_focus_minutes: int = 0
    completed_tasks_today: int = 0
    completed_tasks_week: int = 0
    streak_days: int = 0
    focus_sessions_week: int = 0
    top_task_focus: list[tuple[str, int]] = field(default_factory=list)
    focus_days: list[tuple[str, int]] = field(default_factory=list)
    blocked_sites: list[tuple[str, int]] = field(default_factory=list)
