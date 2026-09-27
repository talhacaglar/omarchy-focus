"""Pomodoro service."""

from __future__ import annotations

import contextlib
import json
from datetime import timedelta

from ..database import Database
from ..exceptions import PomodoroError
from ..models import PomodoroStateSnapshot, SessionPhase, SessionType
from ..notifications import notify
from ..settings import SettingsService
from ..utils import (
    current_boot_id,
    elapsed_seconds,
    focus_app_tui,
    json_dumps,
    parse_dt,
    play_alert_sound,
    poke_status_bar,
    remaining_seconds,
    to_iso,
    utc_now,
)
from .focus import FocusService
from .tasks import TaskService


class PomodoroService:
    STATE_KEY = "pomodoro.current"
    STREAK_KEY = "pomodoro.work_streak"
    PENDING_BREAK_KEY = "pomodoro.pending_break"

    def __init__(
        self,
        db: Database,
        settings: SettingsService,
        tasks: TaskService,
        focus: FocusService,
    ) -> None:
        self.db = db
        self.settings = settings
        self.tasks = tasks
        self.focus = focus

    def _load_raw(self) -> dict[str, object] | None:
        row = self.db.get_state(self.STATE_KEY)
        return json.loads(row["value_json"]) if row else None

    def _save_raw(self, payload: dict[str, object]) -> None:
        self.db.upsert_state(self.STATE_KEY, json_dumps(payload))

    def _raw_to_snapshot(self, raw: dict[str, object] | None) -> PomodoroStateSnapshot:
        if not raw:
            return PomodoroStateSnapshot()
        return PomodoroStateSnapshot(
            phase=SessionPhase(raw["phase"]),
            session_type=SessionType(raw["session_type"]) if raw.get("session_type") else None,
            started_at=parse_dt(raw.get("started_at")),
            ends_at=parse_dt(raw.get("ends_at")),
            paused_at=parse_dt(raw.get("paused_at")),
            paused_seconds=int(raw.get("paused_seconds", 0)),
            boot_id=str(raw.get("boot_id")) if raw.get("boot_id") else None,
            remaining_seconds=int(raw.get("remaining_seconds", 0)),
            task_id=raw.get("task_id"),
            task_title=raw.get("task_title"),
            cycle_count=int(raw.get("cycle_count", 0)),
            auto_focus=bool(raw.get("auto_focus", False)),
            strict_focus=bool(raw.get("strict_focus", False)),
        )

    def _snapshot_to_raw(self, snapshot: PomodoroStateSnapshot) -> dict[str, object]:
        return {
            "phase": snapshot.phase.value,
            "session_type": snapshot.session_type.value if snapshot.session_type else None,
            "started_at": to_iso(snapshot.started_at),
            "ends_at": to_iso(snapshot.ends_at),
            "paused_at": to_iso(snapshot.paused_at),
            "paused_seconds": snapshot.paused_seconds,
            "boot_id": snapshot.boot_id,
            "remaining_seconds": snapshot.remaining_seconds,
            "task_id": snapshot.task_id,
            "task_title": snapshot.task_title,
            "cycle_count": snapshot.cycle_count,
            "auto_focus": snapshot.auto_focus,
            "strict_focus": snapshot.strict_focus,
        }

    def _current_streak(self) -> int:
        row = self.db.get_state(self.STREAK_KEY)
        if not row:
            return 0
        payload = json.loads(row["value_json"])
        return int(payload.get("count", 0))

    def _set_streak(self, value: int) -> None:
        self.db.upsert_state(self.STREAK_KEY, json_dumps({"count": value}))

    def _load_pending_break(self) -> dict[str, object] | None:
        row = self.db.get_state(self.PENDING_BREAK_KEY)
        return json.loads(row["value_json"]) if row else None

    def _save_pending_break(self, payload: dict[str, object]) -> None:
        self.db.upsert_state(self.PENDING_BREAK_KEY, json_dumps(payload))

    def pending_break(self) -> dict[str, object] | None:
        payload = self._load_pending_break()
        if not payload:
            return None
        stored_boot_id = payload.get("boot_id")
        boot_id = current_boot_id()
        if boot_id and stored_boot_id != boot_id:
            self.clear_pending_break()
            return None
        return payload

    def clear_pending_break(self) -> None:
        self.db.delete_state(self.PENDING_BREAK_KEY)

    def snapshot(self) -> PomodoroStateSnapshot:
        return self._raw_to_snapshot(self._load_raw())

    def _clear_if_rebooted(self, raw: dict[str, object] | None) -> PomodoroStateSnapshot | None:
        if not raw:
            self.pending_break()
            return None
        stored_boot_id = raw.get("boot_id")
        boot_id = current_boot_id()
        if not boot_id:
            self.pending_break()
            return None
        if stored_boot_id == boot_id:
            self.pending_break()
            return None

        snapshot = self._raw_to_snapshot(raw)
        if snapshot.phase in {SessionPhase.RUNNING, SessionPhase.PAUSED}:
            self._record_session(snapshot, completed=False, interrupted=True, note="system rebooted")
        self.db.delete_state(self.STATE_KEY)
        self.clear_pending_break()
        poke_status_bar()
        return PomodoroStateSnapshot()

    def status(self) -> PomodoroStateSnapshot:
        self.tick()
        return self._raw_to_snapshot(self._load_raw())

    def start(
        self,
        *,
        task_id: int | None = None,
        minutes: int | None = None,
        auto_focus: bool | None = None,
        strict_focus: bool | None = None,
    ) -> PomodoroStateSnapshot:
        current = self._raw_to_snapshot(self._load_raw())
        if current.phase in {SessionPhase.RUNNING, SessionPhase.PAUSED}:
            self.stop(reason="restarted")

        auto_focus = self.settings.get("focus_on_pomodoro_start") if auto_focus is None else auto_focus
        strict_focus = self.settings.get("strict_mode_default") if strict_focus is None else strict_focus
        duration_minutes = minutes or int(self.settings.get("pomodoro_work_minutes"))
        started_at = utc_now()
        ends_at = started_at + timedelta(minutes=duration_minutes)
        task_title = None
        self.clear_pending_break()
        if task_id:
            task = self.tasks.get_task(task_id)
            task_title = task.title
            if task.status == "pending":
                self.tasks.update_task(task_id, status="in_progress")

        snapshot = PomodoroStateSnapshot(
            phase=SessionPhase.RUNNING,
            session_type=SessionType.WORK,
            started_at=started_at,
            ends_at=ends_at,
            boot_id=current_boot_id(),
            remaining_seconds=duration_minutes * 60,
            task_id=task_id,
            task_title=task_title,
            cycle_count=self._current_streak(),
            auto_focus=bool(auto_focus),
            strict_focus=bool(strict_focus),
        )
        focus_started = False
        if auto_focus:
            self.focus.start(minutes=duration_minutes, strict_mode=strict_focus)
            focus_started = True
        try:
            self._save_raw(self._snapshot_to_raw(snapshot))
        except Exception:
            if focus_started:
                with contextlib.suppress(Exception):
                    self.focus.stop(force=True, interactive=False, reason="Rolled back failed pomodoro start")
            raise
        notify(
            "Pomodoro started",
            task_title or f"{duration_minutes} minute focus session",
            enabled=self.settings.get("notifications_enabled"),
        )
        poke_status_bar()
        return snapshot

    def start_break(self, *, minutes: int | None = None) -> PomodoroStateSnapshot:
        current = self._raw_to_snapshot(self._load_raw())
        if current.phase in {SessionPhase.RUNNING, SessionPhase.PAUSED}:
            self.stop(reason="break restarted")

        pending = self.pending_break() or {}
        break_type_value = str(pending.get("break_type", SessionType.SHORT_BREAK.value))
        break_type = SessionType(break_type_value)
        duration_minutes = minutes or int(
            pending.get("minutes") or self.settings.get("pomodoro_short_break_minutes")
        )
        started_at = utc_now()
        ends_at = started_at + timedelta(minutes=duration_minutes)
        snapshot = PomodoroStateSnapshot(
            phase=SessionPhase.RUNNING,
            session_type=break_type,
            started_at=started_at,
            ends_at=ends_at,
            boot_id=current_boot_id(),
            remaining_seconds=duration_minutes * 60,
            task_id=pending.get("task_id"),
            task_title=pending.get("task_title"),
            cycle_count=int(pending.get("cycle_count", self._current_streak())),
            auto_focus=False,
            strict_focus=False,
        )
        self._save_raw(self._snapshot_to_raw(snapshot))
        self.clear_pending_break()
        notify(
            "Break started",
            f"{duration_minutes} minute break",
            enabled=self.settings.get("notifications_enabled"),
        )
        poke_status_bar()
        return snapshot

    def pause(self) -> PomodoroStateSnapshot:
        snapshot = self.status()
        if snapshot.phase != SessionPhase.RUNNING:
            raise PomodoroError("No running session to pause")
        snapshot.remaining_seconds = remaining_seconds(snapshot.ends_at)
        snapshot.phase = SessionPhase.PAUSED
        snapshot.paused_at = utc_now()
        snapshot.ends_at = None
        self._save_raw(self._snapshot_to_raw(snapshot))
        poke_status_bar()
        return snapshot

    def resume(self) -> PomodoroStateSnapshot:
        snapshot = self.status()
        if snapshot.phase != SessionPhase.PAUSED:
            raise PomodoroError("No paused session to resume")
        now = utc_now()
        if snapshot.paused_at:
            snapshot.paused_seconds += elapsed_seconds(snapshot.paused_at, now)
        snapshot.phase = SessionPhase.RUNNING
        snapshot.started_at = snapshot.started_at or now
        snapshot.paused_at = None
        snapshot.ends_at = now + timedelta(seconds=snapshot.remaining_seconds)
        snapshot.boot_id = current_boot_id()
        self._save_raw(self._snapshot_to_raw(snapshot))
        poke_status_bar()
        return snapshot

    def stop(self, *, reason: str = "stopped") -> PomodoroStateSnapshot:
        raw = self._load_raw()
        if not raw:
            return PomodoroStateSnapshot()
        snapshot = self._raw_to_snapshot(raw)
        self._record_session(snapshot, completed=False, interrupted=True, note=reason)
        self.db.delete_state(self.STATE_KEY)
        if snapshot.auto_focus and self.focus.status(check_expiry=False).active:
            with contextlib.suppress(Exception):
                self.focus.stop(force=True, reason="Focus session ended with pomodoro")
        poke_status_bar()
        return PomodoroStateSnapshot()

    def toggle(self) -> PomodoroStateSnapshot:
        snapshot = self.status()
        if snapshot.phase == SessionPhase.IDLE:
            return self.start()
        return self.stop(reason="toggle")

    def tick(self) -> PomodoroStateSnapshot:
        raw = self._load_raw()
        rebooted_snapshot = self._clear_if_rebooted(raw)
        if rebooted_snapshot is not None:
            return rebooted_snapshot
        snapshot = self._raw_to_snapshot(raw)
        if snapshot.phase != SessionPhase.RUNNING or not snapshot.ends_at:
            return snapshot
        remaining = remaining_seconds(snapshot.ends_at)
        if remaining > 0:
            snapshot.remaining_seconds = remaining
            self._save_raw(self._snapshot_to_raw(snapshot))
            return snapshot

        if snapshot.session_type == SessionType.WORK:
            self._record_session(snapshot, completed=True, interrupted=False, note="work complete")
            streak = self._current_streak() + 1
            self._set_streak(streak)
            break_type = SessionType.SHORT_BREAK
            minutes = int(self.settings.get("pomodoro_short_break_minutes"))
            self.db.delete_state(self.STATE_KEY)
            self._save_pending_break(
                {
                    "prompt_id": f"break-{utc_now().timestamp():.0f}",
                    "break_type": break_type.value,
                    "minutes": minutes,
                    "boot_id": current_boot_id(),
                    "task_id": snapshot.task_id,
                    "task_title": snapshot.task_title,
                    "cycle_count": streak,
                    "created_at": to_iso(utc_now()),
                }
            )
            if snapshot.auto_focus and self.focus.status(check_expiry=False).active:
                with contextlib.suppress(Exception):
                    self.focus.stop(force=True, interactive=False, reason="Work session complete")
            notify(
                "Pomodoro complete",
                f"{minutes} minute break is ready",
                enabled=self.settings.get("notifications_enabled"),
            )
            play_alert_sound()
            focus_app_tui()
            poke_status_bar()
            return PomodoroStateSnapshot()

        self._record_session(snapshot, completed=True, interrupted=False, note="break complete")
        self.db.delete_state(self.STATE_KEY)
        notify(
            "Break complete",
            "Ready for the next focus session",
            enabled=self.settings.get("notifications_enabled"),
        )
        poke_status_bar()
        return PomodoroStateSnapshot()

    def _record_session(
        self,
        snapshot: PomodoroStateSnapshot,
        *,
        completed: bool,
        interrupted: bool,
        note: str,
    ) -> None:
        if not snapshot.started_at or not snapshot.session_type:
            return
        effective_end = utc_now()
        if completed and snapshot.ends_at:
            effective_end = snapshot.ends_at
        elif snapshot.paused_at:
            effective_end = snapshot.paused_at
        duration = max(0, elapsed_seconds(snapshot.started_at, effective_end) - snapshot.paused_seconds)
        self.db.execute(
            """
            INSERT INTO pomodoro_sessions (
                task_id, session_type, state, started_at, ended_at,
                duration_seconds, completed, interrupted, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.task_id,
                snapshot.session_type.value,
                snapshot.phase.value,
                to_iso(snapshot.started_at),
                to_iso(utc_now()),
                duration,
                1 if completed else 0,
                1 if interrupted else 0,
                note,
            ),
        )
