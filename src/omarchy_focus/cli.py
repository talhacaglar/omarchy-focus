"""CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any

from . import __version__
from .bar import build_state_payload, render_bar
from .bootstrap import build_services
from .exceptions import FocusModeError, OmarchyFocusError, PomodoroError, TaskNotFoundError
from .models import TaskFilters, TaskPriority, TaskStatus
from .paths import APP_NAME
from .utils import (
    acquire_tui_lock,
    clear_tui_window_state,
    focus_existing_tui,
    format_datetime,
    minutes_to_label,
    seconds_to_clock,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omarchy-focus", description=f"{APP_NAME}: tasks, pomodoro timer and site blocking"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("tui")
    subparsers.add_parser("raise")

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--json", action="store_true")

    bar_parser = subparsers.add_parser("bar", help="Render Omarchy bar status")
    bar_parser.add_argument("--plain", action="store_true")

    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--task-id", type=int)
    start_parser.add_argument("--minutes", type=int)
    focus_group = start_parser.add_mutually_exclusive_group()
    focus_group.add_argument(
        "--focus",
        dest="focus",
        action="store_true",
        default=None,
        help="Also enable focus mode for this session",
    )
    focus_group.add_argument(
        "--no-focus",
        dest="focus",
        action="store_false",
        help="Do not enable focus mode even if focus_on_pomodoro_start is set",
    )
    start_parser.add_argument("--strict", action="store_true")

    subparsers.add_parser("pause")
    subparsers.add_parser("resume")
    subparsers.add_parser("stop")
    subparsers.add_parser("toggle")

    widget_parser = subparsers.add_parser("widget", help="Install the Omarchy Shell bar widget")
    widget_parser.add_argument("action", choices=["install", "remove", "path"])
    widget_parser.add_argument(
        "--no-place", action="store_true", help="Copy files but leave the bar layout alone"
    )

    break_parser = subparsers.add_parser("break", help="Start or skip the break that is waiting")
    break_parser.add_argument("action", choices=["start", "skip"], nargs="?", default="start")
    break_parser.add_argument("--minutes", type=int)

    add_task_parser = subparsers.add_parser("add-task")
    add_task_parser.add_argument("title")
    add_task_parser.add_argument("--description", default="")
    add_task_parser.add_argument(
        "--priority", choices=[item.value for item in TaskPriority], default="medium"
    )
    add_task_parser.add_argument("--tags", default="")
    add_task_parser.add_argument("--estimate", type=int)
    add_task_parser.add_argument("--due")

    stats_parser = subparsers.add_parser("stats")
    stats_output = stats_parser.add_mutually_exclusive_group()
    stats_output.add_argument("--json", action="store_true")
    stats_output.add_argument(
        "--md",
        action="store_true",
        help="Render a Markdown report (handy for daily/weekly retrospectives)",
    )
    stats_parser.add_argument("--weeks", type=int, default=17, help="Heatmap length in weeks")

    tasks_parser = subparsers.add_parser("tasks")
    tasks_subparsers = tasks_parser.add_subparsers(dest="tasks_command", required=True)

    tasks_list = tasks_subparsers.add_parser("list")
    tasks_list.add_argument("--search", default="")
    tasks_list.add_argument("--status", choices=[item.value for item in TaskStatus])
    tasks_list.add_argument("--today", action="store_true")
    tasks_list.add_argument("--completed", action="store_true")
    tasks_list.add_argument("--sort", default="updated_desc")

    tasks_done = tasks_subparsers.add_parser("done")
    tasks_done.add_argument("task_id", type=int)

    tasks_delete = tasks_subparsers.add_parser("delete")
    tasks_delete.add_argument("task_id", type=int)

    tasks_edit = tasks_subparsers.add_parser("edit")
    tasks_edit.add_argument("task_id", type=int)
    tasks_edit.add_argument("--title")
    tasks_edit.add_argument("--description")
    tasks_edit.add_argument("--priority", choices=[item.value for item in TaskPriority])
    tasks_edit.add_argument("--tags")
    tasks_edit.add_argument("--estimate", type=int)
    tasks_edit.add_argument("--due")
    tasks_edit.add_argument("--status", choices=[item.value for item in TaskStatus])

    focus_parser = subparsers.add_parser("focus")
    focus_subparsers = focus_parser.add_subparsers(dest="focus_command", required=True)

    focus_on = focus_subparsers.add_parser("on")
    focus_on.add_argument("--minutes", type=int)
    focus_on.add_argument("--strict", action="store_true")
    focus_on.add_argument("--site", action="append", default=[])

    focus_off = focus_subparsers.add_parser("off")
    focus_off.add_argument("--force", action="store_true")

    focus_status = focus_subparsers.add_parser("status")
    focus_status.add_argument("--json", action="store_true")

    focus_subparsers.add_parser("recover")

    focus_add_site = focus_subparsers.add_parser("add-site")
    focus_add_site.add_argument("domain")
    focus_add_site.add_argument("--disabled", action="store_true")

    focus_edit_site = focus_subparsers.add_parser("edit-site")
    focus_edit_site.add_argument("domain")
    focus_edit_site.add_argument("--new-domain")
    focus_edit_site.add_argument("--enabled", choices=["true", "false"])

    focus_enable_site = focus_subparsers.add_parser("enable-site")
    focus_enable_site.add_argument("domain")

    focus_disable_site = focus_subparsers.add_parser("disable-site")
    focus_disable_site.add_argument("domain")

    focus_remove_site = focus_subparsers.add_parser("remove-site")
    focus_remove_site.add_argument("domain")

    settings_parser = subparsers.add_parser("settings")
    settings_subparsers = settings_parser.add_subparsers(dest="settings_command", required=True)

    settings_show = settings_subparsers.add_parser("show")
    settings_show.add_argument("--json", action="store_true")

    settings_set = settings_subparsers.add_parser("set")
    settings_set.add_argument("key")
    settings_set.add_argument("value")

    return parser


def _launch_tui() -> int:
    try:
        from .tui.app import OmarchyFocusApp
    except ImportError as exc:
        print(
            "Textual is not installed. Install dependencies with `python -m pip install -e .` first.",
            file=sys.stderr,
        )
        if "--debug-import" in sys.argv:
            raise exc
        return 1

    lock_handle = acquire_tui_lock()
    if lock_handle is None:
        focus_existing_tui()
        return 0

    app = OmarchyFocusApp()
    try:
        app.run()
    finally:
        clear_tui_window_state()
        lock_handle.close()
    return 0


def _render_stats_terminal(services: Any, weeks: int) -> str:
    """Human stats report with a focus heatmap and peak hours."""
    import os

    from .charts import goal_bar, peak_window, render_heatmap, render_hours

    stats = services.stats.snapshot()
    goal = int(services.settings.get("daily_goal_minutes") or 0) or 150
    color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    days = services.stats.daily_minutes(days=max(1, weeks) * 7)
    hours = services.stats.hourly_minutes(days=30)
    finished = stats.completed_sessions_week
    total = finished + stats.interrupted_sessions_week
    rate = f"{round(100 * finished / total)}%" if total else "—"
    bold = (lambda text: f"\x1b[1m{text}\x1b[0m") if color else (lambda text: text)
    lines = [
        bold(f"{APP_NAME} · {len(days) // 7} weeks"),
        "",
        f"Today   {goal_bar(stats.today_focus_minutes, goal)}  "
        f"{minutes_to_label(stats.today_focus_minutes)} / {minutes_to_label(goal)}"
        f"  ·  {stats.today_completed_pomodoros} pomodoros  ·  {stats.completed_tasks_today} tasks",
        f"Week    {minutes_to_label(stats.week_focus_minutes)}  ·  {stats.streak_days}d streak"
        f"  ·  {rate} sessions finished",
        "",
        render_heatmap(days, goal, style="ansi" if color else "plain"),
        "",
        bold("Focus by hour (30 days)"),
        render_hours(hours),
    ]
    peak = peak_window(hours)
    if peak:
        start, _ = peak
        lines.append(f"Peak: {start:02d}:00–{(start + 2) % 24:02d}:00")
    return "\n".join(lines)


def _render_status(services: Any, *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(build_state_payload(services), ensure_ascii=False, indent=2)
    services.sync()
    pomodoro = services.pomodoro.snapshot()
    pending_break = services.pomodoro.pending_break()
    focus = services.focus.snapshot()
    pending = services.tasks.count_pending()
    if pomodoro.phase.value == "running" and pomodoro.session_type:
        session_label = "Pomodoro" if pomodoro.session_type.value == "work" else "Break"
        task_suffix = f" | {pomodoro.task_title}" if pomodoro.task_title else ""
        return f"{session_label}: {seconds_to_clock(pomodoro.remaining_seconds)} left{task_suffix}"
    if pomodoro.phase.value == "paused":
        return f"Paused: {seconds_to_clock(pomodoro.remaining_seconds)} left"
    if pending_break:
        minutes = int(pending_break.get("minutes", 10))
        return f"Pomodoro complete | Break ready: {minutes}m"
    if focus.active:
        strict = " | strict" if focus.strict_mode else ""
        return f"Focus: ON{strict} | {len(focus.blocked_sites)} site(s) blocked"
    return f"Idle | {pending} pending task(s)"


def _render_stats_markdown(stats: Any) -> str:
    """Render a stats snapshot as a Markdown retrospective report."""
    from datetime import date

    lines = [
        f"# {APP_NAME} — Report ({date.today().isoformat()})",
        "",
        "## Today",
        f"- Completed pomodoros: **{stats.today_completed_pomodoros}**",
        f"- Focus time: **{minutes_to_label(stats.today_focus_minutes)}**",
        f"- Completed tasks: **{stats.completed_tasks_today}**",
        "",
        "## This week",
        f"- Focus time: **{minutes_to_label(stats.week_focus_minutes)}**",
        f"- Completed tasks: **{stats.completed_tasks_week}**",
        f"- Focus sessions: **{stats.focus_sessions_week}**",
        f"- Current streak: **{stats.streak_days} day(s)**",
    ]
    if stats.top_task_focus:
        lines += ["", "## Top tasks (by focus time)"]
        lines += [f"- {title}: {minutes_to_label(minutes)}" for title, minutes in stats.top_task_focus]
    if stats.blocked_sites:
        lines += ["", "## Most-blocked sites"]
        lines += [f"- {site}: {count} session(s)" for site, count in stats.blocked_sites]
    if stats.focus_days:
        lines += ["", "## Daily focus (last 7 days)"]
        lines += [f"- {label}: {minutes_to_label(minutes)}" for label, minutes in stats.focus_days]
    return "\n".join(lines)


def _coerce_setting(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if value.isdigit():
        return int(value)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    normalized_argv = list(sys.argv[1:] if argv is None else argv)
    if normalized_argv and normalized_argv[0] == "waybar":
        normalized_argv[0] = "bar"
    args = parser.parse_args(normalized_argv)
    if not args.command:
        return _launch_tui()

    if args.command == "widget":
        # No database needed; keep this usable before first run.
        from .widget import WIDGET_SOURCE, install_widget, remove_widget

        if args.action == "path":
            print(WIDGET_SOURCE)
            return 0
        try:
            messages = (
                install_widget(place=not args.no_place) if args.action == "install" else remove_widget()
            )
        except (RuntimeError, ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print("\n".join(messages))
        return 0

    services = build_services()

    try:
        if args.command == "tui":
            return _launch_tui()
        if args.command == "raise":
            return 0 if focus_existing_tui() else 1
        if args.command == "status":
            print(_render_status(services, as_json=args.json))
            return 0
        if args.command == "bar":
            print(render_bar(services, json_mode=not args.plain))
            return 0
        if args.command == "start":
            snapshot = services.pomodoro.start(
                task_id=args.task_id,
                minutes=args.minutes,
                auto_focus=args.focus,
                strict_focus=args.strict,
            )
            print(
                f"Started {snapshot.session_type.value if snapshot.session_type else 'session'} for {seconds_to_clock(snapshot.remaining_seconds)}"
            )
            return 0
        if args.command == "pause":
            snapshot = services.pomodoro.pause()
            print(f"Paused at {seconds_to_clock(snapshot.remaining_seconds)}")
            return 0
        if args.command == "resume":
            snapshot = services.pomodoro.resume()
            print(f"Resumed {snapshot.session_type.value if snapshot.session_type else 'session'}")
            return 0
        if args.command == "stop":
            services.pomodoro.stop()
            print("Pomodoro stopped")
            return 0
        if args.command == "toggle":
            snapshot = services.pomodoro.toggle()
            print(snapshot.phase.value)
            return 0
        if args.command == "break":
            services.sync()
            if args.action == "skip":
                services.pomodoro.skip_break()
                print("Break skipped")
                return 0
            snapshot = services.pomodoro.start_break(minutes=args.minutes)
            print(
                f"Started {snapshot.session_type.value if snapshot.session_type else 'session'} for {seconds_to_clock(snapshot.remaining_seconds)}"
            )
            return 0
        if args.command == "add-task":
            task = services.tasks.add_task(
                args.title,
                description=args.description,
                priority=args.priority,
                tags=args.tags,
                estimated_minutes=args.estimate,
                due_at=args.due,
            )
            print(f"Created task #{task.id}: {task.title}")
            return 0
        if args.command == "stats":
            stats = services.stats.snapshot()
            if args.json:
                print(json.dumps(stats.__dict__, ensure_ascii=False, indent=2))
            elif args.md:
                print(_render_stats_markdown(stats))
            else:
                print(_render_stats_terminal(services, args.weeks))
            return 0
        if args.command == "tasks":
            if args.tasks_command == "list":
                filters = TaskFilters(
                    search=args.search,
                    status=TaskStatus(args.status) if args.status else None,
                    today=args.today,
                    completed=args.completed,
                    sort_by=args.sort,
                )
                tasks = services.tasks.list_tasks(filters)
                if not tasks:
                    print("No tasks found.")
                    return 0
                for task in tasks:
                    tags = f" [{' '.join('#' + tag for tag in task.tags)}]" if task.tags else ""
                    due = f" | due {format_datetime(task.due_at)}" if task.due_at else ""
                    estimate = (
                        f" | est {minutes_to_label(task.estimated_minutes)}" if task.estimated_minutes else ""
                    )
                    print(
                        f"{task.id:>3}  {task.priority.value:<6}  {task.status.value:<11}  {task.title}{tags}{estimate}{due}"
                    )
                return 0
            if args.tasks_command == "done":
                task = services.tasks.complete_task(
                    args.task_id,
                    notifications_enabled=services.settings.get("notifications_enabled"),
                )
                print(f"Completed: {task.title}")
                return 0
            if args.tasks_command == "delete":
                services.tasks.delete_task(args.task_id)
                print(f"Deleted task #{args.task_id}")
                return 0
            if args.tasks_command == "edit":
                task = services.tasks.update_task(
                    args.task_id,
                    title=args.title,
                    description=args.description,
                    priority=args.priority,
                    tags=args.tags,
                    estimated_minutes=args.estimate,
                    due_at=args.due,
                    status=args.status,
                )
                print(f"Updated task #{task.id}: {task.title}")
                return 0
        if args.command == "focus":
            if args.focus_command == "on":
                guard = services.focus.start(
                    minutes=args.minutes,
                    strict_mode=args.strict,
                    sites=args.site or None,
                )
                print(f"Focus mode active with {len(guard.blocked_sites)} site(s)")
                return 0
            if args.focus_command == "off":
                services.focus.stop(force=args.force)
                print("Focus mode disabled")
                return 0
            if args.focus_command == "status":
                guard = services.focus.status()
                if args.json:
                    print(json.dumps(asdict(guard), ensure_ascii=False, indent=2, default=str))
                else:
                    if guard.active:
                        print(f"Focus ON | strict={guard.strict_mode} | blocked={len(guard.blocked_sites)}")
                    else:
                        print("Focus OFF")
                return 0
            if args.focus_command == "recover":
                guard = services.focus.recover()
                print("recovered" if guard.active else "idle")
                return 0
            if args.focus_command == "add-site":
                services.focus.add_site(args.domain, enabled=not args.disabled)
                print(f"Added blocked site: {args.domain}")
                return 0
            if args.focus_command == "edit-site":
                enabled = None
                if args.enabled is not None:
                    enabled = args.enabled == "true"
                updated = services.focus.update_site(
                    args.domain,
                    new_domain=args.new_domain,
                    enabled=enabled,
                )
                print(f"Updated blocked site: {updated}")
                return 0
            if args.focus_command == "enable-site":
                services.focus.toggle_site(args.domain, True)
                print(f"Enabled blocked site: {args.domain}")
                return 0
            if args.focus_command == "disable-site":
                services.focus.toggle_site(args.domain, False)
                print(f"Disabled blocked site: {args.domain}")
                return 0
            if args.focus_command == "remove-site":
                services.focus.remove_site(args.domain)
                print(f"Removed blocked site: {args.domain}")
                return 0
        if args.command == "settings":
            if args.settings_command == "show":
                values = services.settings.all()
                if args.json:
                    print(json.dumps(values, ensure_ascii=False, indent=2))
                else:
                    for key, value in values.items():
                        print(f"{key}={value}")
                return 0
            if args.settings_command == "set":
                services.settings.set(args.key, _coerce_setting(args.value))
                print(f"Updated setting: {args.key}")
                return 0
    except (OmarchyFocusError, TaskNotFoundError, PomodoroError, FocusModeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
