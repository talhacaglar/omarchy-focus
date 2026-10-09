"""Main Textual application."""

from __future__ import annotations

import math
from typing import Any

from rich.markup import escape
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.theme import Theme
from textual.timer import Timer
from textual.widgets import Button, DataTable, Footer, Header, Input, Static, TabbedContent, TabPane

from ..bootstrap import build_services
from ..charts import color_bar, peak_window, render_heatmap, render_hours, week_columns
from ..models import (
    FocusStateSnapshot,
    PomodoroStateSnapshot,
    SessionPhase,
    SessionType,
    StatsSnapshot,
    Task,
    TaskFilters,
)
from ..paths import APP_NAME
from ..utils import (
    format_datetime,
    minutes_to_label,
    register_tui_window,
    remaining_seconds,
    seconds_to_clock,
)
from .dialogs import (
    BlockedSitesScreen,
    BreakPromptScreen,
    ConfirmScreen,
    FilterScreen,
    QuickAddTaskScreen,
    SettingEditScreen,
    TaskEditorResult,
    TaskEditorScreen,
)

# Signature "midnight gold" dark theme: deep blue-steel surfaces with warm
# gold accents. The custom $gold / $gold-soft variables are consumed by
# app.tcss so the branded accent survives theme switches.
MIDNIGHT_GOLD = Theme(
    name="midnight-gold",
    primary="#b8984e",
    secondary="#5b7bb4",
    accent="#f6e4b2",
    success="#8dd3b4",
    warning="#f6d47c",
    error="#f09aa6",
    foreground="#dbe4ff",
    background="#070b12",
    surface="#0b111b",
    panel="#0f1522",
    dark=True,
    variables={
        "gold": "#b8984e",
        "gold-soft": "#f6e4b2",
    },
)

# Light counterpart: warm parchment surfaces with the same gold accent, tuned
# for readable contrast in bright environments.
DAYLIGHT_GOLD = Theme(
    name="daylight-gold",
    primary="#9a7b32",
    secondary="#3b5c94",
    accent="#8a6d24",
    success="#2b8a58",
    warning="#b8860b",
    error="#c0392b",
    foreground="#1b2330",
    background="#f5f2ea",
    surface="#fffdf7",
    panel="#efe9db",
    dark=False,
    variables={
        "gold": "#9a7b32",
        "gold-soft": "#7a5f1e",
    },
)

# Persisted in the settings table under this key.
THEME_SETTING_KEY = "theme_variant"
THEMES_BY_NAME = {MIDNIGHT_GOLD.name: MIDNIGHT_GOLD, DAYLIGHT_GOLD.name: DAYLIGHT_GOLD}

SETTING_LABELS = {
    "default_view": "Start view",
    "focus_auto_release": "Auto-release focus",
    "focus_on_pomodoro_start": "Focus with timer",
    "notifications_enabled": "Notifications",
    "pomodoro_long_break_every": "Long break interval",
    "pomodoro_long_break_minutes": "Long break",
    "pomodoro_short_break_minutes": "Short break",
    "pomodoro_work_minutes": "Focus duration",
    "strict_mode_default": "Strict focus",
    "theme_variant": "Theme",
    "bar_output_mode": "Bar output",
    "daily_goal_minutes": "Daily goal (min)",
    "open_app_on_complete": "Open app when done",
}


class OmarchyFocusApp(App[None]):
    """Omarchy Focus terminal app."""

    CSS_PATH = "app.tcss"
    TITLE = APP_NAME
    SUB_TITLE = "One task. One timer. No noise."

    BINDINGS = [
        Binding("q", "app_quit", "Quit"),
        Binding("a", "add_task", "Add"),
        Binding("e", "edit_selected", "Edit", show=False),
        Binding("d", "delete_selected", "Delete", show=False),
        Binding("x", "complete_selected", "Done"),
        Binding("slash", "search_tasks", "Search"),
        Binding("f", "filter_tasks", "Filter", show=False),
        Binding("s", "toggle_pomodoro", "Timer"),
        Binding("p", "pause_resume", "Pause", show=False),
        Binding("m", "toggle_focus", "Focus"),
        Binding("b", "show_blocked_sites", "Sites", show=False),
        Binding("t", "show_tasks", "Tasks", show=False),
        Binding("g", "show_dashboard", "Now", show=False),
        Binding("i", "show_statistics", "Stats", show=False),
        Binding("comma", "show_settings", "Settings", show=False),
        Binding("f2", "toggle_theme", "Theme", show=False),
        Binding("question_mark", "show_help", "Help"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.services = build_services()
        # Register and select the theme before the app's CSS is parsed so the
        # custom $gold / $gold-soft variables from app.tcss resolve correctly.
        self.register_theme(MIDNIGHT_GOLD)
        self.register_theme(DAYLIGHT_GOLD)
        saved_theme = self.services.settings.get(THEME_SETTING_KEY, MIDNIGHT_GOLD.name)
        self.theme = saved_theme if saved_theme in THEMES_BY_NAME else MIDNIGHT_GOLD.name
        self.filters = TaskFilters(sort_by="priority_desc")
        self.selected_task_id: int | None = None
        self.selected_focus_domain: str | None = None
        self.selected_setting_key: str | None = None
        self._pending_break_prompt_id: str | None = None
        self._cached_pomodoro = PomodoroStateSnapshot()
        self._cached_focus = FocusStateSnapshot()
        self._cached_stats = StatsSnapshot()
        self._cached_heatmap: list[tuple[str, int]] = []
        self._cached_hours: list[int] = [0] * 24
        self._cached_pending_break: dict[str, object] | None = None
        self._cached_pending_count = 0
        self._cached_enabled_sites = 0
        self._cached_done_today = 0
        self._task_row_map: dict[str, list[int]] = {}
        self._site_row_map: list[str] = []
        self._setting_row_map: list[str] = []
        self._task_table_signatures: dict[str, tuple[tuple[str, ...], ...]] = {}
        self._site_table_signature: tuple[tuple[str, ...], ...] = ()
        self._settings_table_signature: tuple[tuple[str, ...], ...] = ()
        self._search_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="app-shell"):
            with Horizontal(id="status-bar"):
                yield Static(
                    f"󰄛  {APP_NAME.upper()}\nNext move, clearly.",
                    id="brand-card",
                )
                yield Static(id="pomodoro-chip", classes="status-chip")
                yield Static(id="focus-chip", classes="status-chip")
                yield Static(id="task-chip", classes="status-chip")
            with TabbedContent(initial=str(self.services.settings.get("default_view")), id="views"):
                with TabPane("Now", id="dashboard"), Horizontal(id="dashboard-layout"):
                    with Vertical(id="dashboard-main"):
                        yield Static(id="dashboard-now", classes="hero-panel")
                        with Horizontal(id="dashboard-actions"):
                            yield Button("Start / stop  (s)", id="start-session", variant="primary")
                            yield Button("Add task  (a)", id="add-task")
                            yield Button("Start focus guard  (m)", id="focus-toggle")
                        with Vertical(id="dashboard-tasks-panel", classes="panel"):
                            yield Static("UP NEXT", classes="eyebrow")
                            yield DataTable(id="dashboard-tasks")
                            yield Static(
                                "Queue clear. Press a to capture your next move.",
                                id="dashboard-empty",
                                classes="empty-state",
                            )
                    with Vertical(id="dashboard-side"):
                        yield Static(id="dashboard-day", classes="panel")
                        yield Static(id="dashboard-focus", classes="panel")
                        yield Static(id="dashboard-stats", classes="panel")
                with TabPane("Tasks", id="tasks"), Horizontal(id="tasks-layout"):
                    with Vertical(id="tasks-main"):
                        yield Static("TASKS", classes="view-title")
                        yield Input(placeholder="Type to search tasks…", id="task-search")
                        yield Static(id="task-filter-summary", classes="filter-line")
                        yield DataTable(id="tasks-table")
                        yield Static(
                            "No matching tasks. Change the search or press a to add one.",
                            id="tasks-empty",
                            classes="empty-state",
                        )
                    with Vertical(id="tasks-side"):
                        yield Static(id="task-detail", classes="panel")
                        yield Static(id="task-quick-actions", classes="panel")
                with TabPane("Focus Session", id="focus"), Horizontal(id="focus-layout"):
                    with Vertical(id="focus-main"):
                        yield Static(id="focus-status", classes="panel")
                        yield DataTable(id="focus-sites-table")
                    with Vertical(id="focus-side"):
                        yield Static(id="focus-controls", classes="panel")
                        yield Static(id="focus-history", classes="panel")
                with TabPane("Statistics", id="statistics"):  # noqa: SIM117 - Textual compose tree
                    with Horizontal(id="statistics-layout"):
                        with Vertical(id="stats-main"):
                            yield Static(id="stats-overview", classes="panel")
                            yield Static(id="stats-charts", classes="panel")
                        with Vertical(id="stats-side"):
                            yield Static(id="stats-tasks", classes="panel")
                            yield Static(id="stats-focus", classes="panel")
                with TabPane("Settings", id="settings"), Horizontal(id="settings-layout"):
                    with Vertical(id="settings-main"):
                        yield Static(id="settings-summary", classes="panel")
                        yield DataTable(id="settings-table")
                    with Vertical(id="settings-side"):
                        yield Static(id="settings-hints", classes="panel")
                with TabPane("Help", id="help"):
                    yield Static(id="help-pane")
        yield Footer()

    def on_mount(self) -> None:
        self._configure_tables()
        register_tui_window()
        self.set_timer(0.5, register_tui_window)
        self.set_interval(1.0, self.refresh_live_data)
        self.set_interval(5.0, self.refresh_data)
        self.refresh_data()

    def on_resize(self, event: events.Resize) -> None:
        """Keep the primary workflow usable in narrower terminal windows."""
        self.set_class(event.size.width < 105, "compact")

    def _configure_tables(self) -> None:
        for table_id in ("dashboard-tasks", "tasks-table"):
            table = self.query_one(f"#{table_id}", DataTable)
            table.cursor_type = "row"
            table.add_columns("ID", "Title", "Priority", "Status", "Due")
        sites_table = self.query_one("#focus-sites-table", DataTable)
        sites_table.cursor_type = "row"
        sites_table.add_columns("Domain", "Enabled", "Source")
        settings_table = self.query_one("#settings-table", DataTable)
        settings_table.cursor_type = "row"
        settings_table.add_columns("Setting", "Value")

    def _sync_live_cache(self) -> None:
        self.services.sync()
        self._cached_pomodoro = self.services.pomodoro.snapshot()
        self._cached_pending_break = self.services.pomodoro.pending_break()
        self._cached_focus = self.services.focus.snapshot()

    def refresh_live_data(self) -> None:
        """Refresh countdowns without rebuilding tables or stealing input focus."""
        self._sync_live_cache()
        self._refresh_top_chips()
        self._refresh_dashboard_now()
        self._refresh_dashboard_focus()
        self._handle_pending_break_prompt()

    def refresh_data(self) -> None:
        """Refresh slower-changing data and table contents."""
        self._sync_live_cache()
        self._cached_stats = self.services.stats.snapshot()
        self._cached_heatmap = self.services.stats.daily_minutes(days=17 * 7)
        self._cached_hours = self.services.stats.hourly_minutes(days=30)
        self._cached_pending_count = self.services.tasks.count_pending()
        self._cached_enabled_sites = len(self.services.focus.list_sites(enabled_only=True))
        self._cached_done_today = self.services.tasks.count_done_today()
        self._refresh_top_chips()
        self._refresh_dashboard()
        self._refresh_tasks()
        self._refresh_focus()
        self._refresh_stats()
        self._refresh_settings()
        self._refresh_help()
        self._handle_pending_break_prompt()

    def _refresh_top_chips(self) -> None:
        pomodoro = self._cached_pomodoro
        focus = self._cached_focus
        pending = self._cached_pending_count
        pending_break = self._cached_pending_break
        pomodoro_text = "󰄉 Idle\nReady for deep work"
        if pomodoro.phase == SessionPhase.RUNNING:
            label = "Work" if pomodoro.session_type == SessionType.WORK else "Break"
            pomodoro_text = f"󰄉 {label}\n{seconds_to_clock(pomodoro.remaining_seconds)} left"
        elif pomodoro.phase == SessionPhase.PAUSED:
            pomodoro_text = f"󰄉 Paused\n{seconds_to_clock(pomodoro.remaining_seconds)} left"
        elif pending_break:
            pomodoro_text = f"󰁅 Break Ready\n{pending_break.get('minutes', 10)}m waiting"
        focus_text = "󰈈 Focus\nOff"
        if focus.active:
            strict = "strict" if focus.strict_mode else "adaptive"
            left = seconds_to_clock(remaining_seconds(focus.ends_at)) if focus.ends_at else "manual"
            focus_text = f"󰈈 {strict.title()}\n{left} · {len(focus.blocked_sites)} sites"
        task_text = f" Queue\n{pending} open · {self._cached_done_today} done"
        self.query_one("#pomodoro-chip", Static).update(pomodoro_text)
        self.query_one("#focus-chip", Static).update(focus_text)
        self.query_one("#task-chip", Static).update(task_text)

    def _handle_pending_break_prompt(self) -> None:
        pending_break = self.services.pomodoro.pending_break()
        if not pending_break:
            self._pending_break_prompt_id = None
            return

        prompt_id = str(pending_break.get("prompt_id") or "")
        if not prompt_id or prompt_id == self._pending_break_prompt_id:
            return

        self._pending_break_prompt_id = prompt_id
        self.show_view("dashboard")
        self.push_screen(
            BreakPromptScreen(
                minutes=int(pending_break.get("minutes", 10)),
                task_title=str(pending_break.get("task_title") or "") or None,
            ),
            lambda accepted: self._handle_break_prompt_result(prompt_id, accepted),
        )

    def _handle_break_prompt_result(self, prompt_id: str, accepted: bool) -> None:
        pending_break = self.services.pomodoro.pending_break()
        if not pending_break or str(pending_break.get("prompt_id") or "") != prompt_id:
            self.refresh_data()
            return

        if accepted:
            self.services.pomodoro.start_break(minutes=int(pending_break.get("minutes", 10)))
        else:
            self.services.pomodoro.clear_pending_break()
        self.refresh_data()

    def _task_table_rows(self) -> list[Task]:
        return self.services.tasks.list_tasks(self.filters)

    def _populate_task_table(self, table_id: str, tasks: list[Task]) -> None:
        table = self.query_one(f"#{table_id}", DataTable)
        empty = self.query_one(f"#{'dashboard-empty' if table_id == 'dashboard-tasks' else 'tasks-empty'}")
        table.display = bool(tasks)
        empty.display = not tasks
        rows = tuple(
            (
                str(task.id),
                task.title[:42],
                task.priority.value,
                task.status.value.replace("_", " "),
                format_datetime(task.due_at) if task.due_at else "—",
            )
            for task in tasks
        )
        if self._task_table_signatures.get(table_id) == rows:
            return

        self._task_table_signatures[table_id] = rows
        table.clear()
        self._task_row_map[table_id] = [task.id for task in tasks]
        for row in rows:
            table.add_row(*row)
        if tasks and self.selected_task_id is None:
            self.selected_task_id = tasks[0].id
        if self.selected_task_id in self._task_row_map[table_id]:
            table.move_cursor(row=self._task_row_map[table_id].index(self.selected_task_id))

    def _get_task_by_selection(self) -> Task | None:
        if self.selected_task_id is None:
            candidate = self.services.tasks.get_next_focus_candidate()
            if candidate:
                self.selected_task_id = candidate.id
            else:
                return None
        try:
            return self.services.tasks.get_task(self.selected_task_id)
        except Exception:
            return None

    def _refresh_dashboard(self) -> None:
        # Only open work belongs in "Up next"; finished tasks live in Tasks.
        upcoming_tasks = self.services.tasks.list_open(limit=8)
        self._populate_task_table("dashboard-tasks", upcoming_tasks)
        stats = self._cached_stats
        self._refresh_dashboard_now()
        goal = int(self.services.settings.get("daily_goal_minutes") or 0) or 150
        self.query_one("#dashboard-day", Static).update(
            "\n".join(
                [
                    "TODAY",
                    "",
                    color_bar(stats.today_focus_minutes, goal, width=24),
                    f"{minutes_to_label(stats.today_focus_minutes)} of {minutes_to_label(goal)} goal",
                    f"{self._cached_done_today} tasks  ·  {stats.today_completed_pomodoros} focus cycles",
                ]
            )
        )
        self._refresh_dashboard_focus()
        rhythm = week_columns([minutes for _, minutes in stats.focus_days])
        labels = "  ".join(day[:2] for day, _ in stats.focus_days)
        self.query_one("#dashboard-stats", Static).update(
            "\n".join(
                [
                    "7-DAY RHYTHM",
                    "",
                    rhythm or "No focus sessions yet",
                    labels,
                    "",
                    f"{stats.week_focus_minutes}m total  ·  {stats.streak_days}d streak",
                ]
            )
        )

    def _refresh_dashboard_now(self) -> None:
        pomodoro = self._cached_pomodoro
        task = self._get_task_by_selection()
        task_title = pomodoro.task_title or (task.title if task else "Add your first task")
        if pomodoro.phase == SessionPhase.RUNNING:
            phase = "BREAK IN PROGRESS" if pomodoro.session_type != SessionType.WORK else "FOCUS IN PROGRESS"
            state = seconds_to_clock(pomodoro.remaining_seconds)
            hint = "p pause  ·  s stop"
        elif pomodoro.phase == SessionPhase.PAUSED:
            phase = "PAUSED"
            state = seconds_to_clock(pomodoro.remaining_seconds)
            hint = "p resume  ·  s end session"
        else:
            phase = "NOW"
            estimate = minutes_to_label(task.estimated_minutes) if task else "50m default"
            state = f"Ready  ·  {estimate}"
            hint = "s start this task  ·  a capture another"
        self.query_one("#dashboard-now", Static).update("\n".join([phase, "", task_title, "", state, hint]))

    def _refresh_dashboard_focus(self) -> None:
        focus = self._cached_focus
        toggle = self.query_one("#focus-toggle", Button)
        toggle.label = "Stop focus guard  (m)" if focus.active else "Start focus guard  (m)"
        toggle.variant = "warning" if focus.active else "default"
        remaining = seconds_to_clock(remaining_seconds(focus.ends_at)) if focus.ends_at else "manual"
        self.query_one("#dashboard-focus", Static).update(
            "\n".join(
                [
                    "FOCUS GUARD",
                    "",
                    f"{'ACTIVE' if focus.active else 'Off'}  ·  "
                    f"{remaining if focus.active else 'press m to enable'}",
                    f"{len(focus.blocked_sites) if focus.active else self._cached_enabled_sites} sites  ·  "
                    f"{'strict' if focus.strict_mode else 'adaptive'}",
                ]
            )
        )

    def _refresh_tasks(self) -> None:
        tasks = self._task_table_rows()
        task_ids = [task.id for task in tasks]
        if tasks and self.selected_task_id not in task_ids:
            self.selected_task_id = tasks[0].id
        self._populate_task_table("tasks-table", tasks)
        search_input = self.query_one("#task-search", Input)
        if not search_input.has_focus and search_input.value != self.filters.search:
            search_input.value = self.filters.search
        filters = [f"{len(tasks)} shown"]
        if self.filters.status:
            filters.append(self.filters.status.value.replace("_", " "))
        if self.filters.priority:
            filters.append(f"{self.filters.priority.value} priority")
        if self.filters.today:
            filters.append("due / active today")
        if self.filters.completed:
            filters.append("completed")
        filters.append(self.filters.sort_by.replace("_", " "))
        self.query_one("#task-filter-summary", Static).update("  ·  ".join(filters))
        self.query_one("#task-quick-actions", Static).update(
            "\n".join(
                [
                    "Quick Actions",
                    "",
                    "a  add new task",
                    "e  edit selected task",
                    "x  mark selected done",
                    "d  delete selected task",
                    "s  start pomodoro on selection",
                    "/  search",
                    "f  advanced filter",
                ]
            )
        )
        if tasks:
            self._update_task_detail("#task-detail")
        else:
            self.query_one("#task-detail", Static).update(
                "NO MATCHES\n\nClear the search or adjust filters to see your queue."
            )

    def _update_task_detail(self, widget_id: str) -> None:
        task = self._get_task_by_selection()
        if not task:
            self.query_one(widget_id, Static).update(
                "NO TASK SELECTED\n\nPress a to capture the next thing you want to finish."
            )
            return
        lines = [
            f"{task.title}",
            "",
            f"Status         {task.status.value.replace('_', ' ')}",
            f"Priority       {task.priority.value}",
            f"Estimate       {minutes_to_label(task.estimated_minutes)}",
            f"Due            {format_datetime(task.due_at)}",
            f"Tags           {' '.join('#' + tag for tag in task.tags) if task.tags else '—'}",
            "",
            "Notes",
            task.description or "No extra notes.",
        ]
        self.query_one(widget_id, Static).update("\n".join(lines))

    def _refresh_focus(self) -> None:
        focus = self._cached_focus
        sites = self.services.focus.list_sites()
        table = self.query_one("#focus-sites-table", DataTable)
        rows = tuple((domain, "on" if enabled else "off", source) for domain, enabled, source in sites)
        if rows != self._site_table_signature:
            self._site_table_signature = rows
            table.clear()
            self._site_row_map = [domain for domain, _, _ in sites]
            for row in rows:
                table.add_row(*row)
        if self.selected_focus_domain is None and self._site_row_map:
            self.selected_focus_domain = self._site_row_map[0]
        if self.selected_focus_domain:
            for index, domain in enumerate(self._site_row_map):
                if domain == self.selected_focus_domain:
                    table.move_cursor(row=index)
                    break
        remaining = seconds_to_clock(remaining_seconds(focus.ends_at)) if focus.ends_at else "manual"
        self.query_one("#focus-status", Static).update(
            "\n".join(
                [
                    "Focus Session",
                    "",
                    f"Active         {'yes' if focus.active else 'no'}",
                    f"Strict         {'yes' if focus.strict_mode else 'no'}",
                    f"Time left      {remaining}",
                    f"Blocked sites  {len(focus.blocked_sites)}",
                    f"Recovered      {'yes' if focus.recovered else 'no'}",
                    "",
                    "Middle click in the Omarchy bar toggles focus mode.",
                ]
            )
        )
        self.query_one("#focus-controls", Static).update(
            "\n".join(
                [
                    "Focus Controls",
                    "",
                    "m  toggle focus mode",
                    "b  open blocked site manager",
                    "s  start pomodoro + focus manually",
                    "",
                    "Default mode uses your configured blocked sites.",
                ]
            )
        )
        stats = self._cached_stats
        top_blocked = (
            ", ".join(f"{site} ({count})" for site, count in stats.blocked_sites)
            or "No recent focus sessions"
        )
        self.query_one("#focus-history", Static).update(
            "\n".join(
                [
                    "Focus Analytics",
                    "",
                    f"Week sessions  {stats.focus_sessions_week}",
                    f"Week focus     {stats.week_focus_minutes}m",
                    f"Top blocks     {top_blocked}",
                ]
            )
        )

    def _refresh_stats(self) -> None:
        stats = self._cached_stats
        self.query_one("#stats-overview", Static).update(
            "\n".join(
                [
                    "Performance Overview",
                    "",
                    f"Today pomodoros    {stats.today_completed_pomodoros}",
                    f"Today focus        {stats.today_focus_minutes}m",
                    f"Week focus         {stats.week_focus_minutes}m",
                    f"Tasks today        {stats.completed_tasks_today}",
                    f"Tasks this week    {stats.completed_tasks_week}",
                    f"Streak             {stats.streak_days} day(s)",
                    f"Finished sessions  {self._finish_rate(stats)}",
                ]
            )
        )
        chart_values = [minutes for _, minutes in stats.focus_days]
        goal = int(self.services.settings.get("daily_goal_minutes") or 0) or 150
        peak = peak_window(self._cached_hours)
        self.query_one("#stats-charts", Static).update(
            "\n".join(
                [
                    "Focus Heatmap · 17 weeks",
                    "",
                    render_heatmap(self._cached_heatmap, goal, style="rich"),
                    "",
                    "Focus by hour · 30 days",
                    render_hours(self._cached_hours, style="rich"),
                    f"Peak window {peak[0]:02d}:00–{(peak[0] + 2) % 24:02d}:00" if peak else "",
                ]
            )
        )
        top_tasks = (
            "\n".join(f"{escape(title[:22]):<22} {minutes:>4}m" for title, minutes in stats.top_task_focus)
            or "No task-linked sessions yet."
        )
        week_peak = max(chart_values) or 1
        self.query_one("#stats-tasks", Static).update(
            "\n".join(
                [
                    "Last 7 Days",
                    "",
                    *(
                        f"{day[:2]}  {color_bar(minutes, week_peak, width=14)}  {minutes_to_label(minutes)}"
                        for day, minutes in stats.focus_days
                    ),
                    "",
                    "Top Tasks",
                    "",
                    top_tasks,
                ]
            )
        )
        blocked = (
            "\n".join(f"{site:<26} {count}" for site, count in stats.blocked_sites)
            or "No blocked site hits yet."
        )
        self.query_one("#stats-focus", Static).update(
            "\n".join(
                [
                    "Blocked Domains",
                    "",
                    blocked,
                ]
            )
        )

    @staticmethod
    def _finish_rate(stats: StatsSnapshot) -> str:
        attempted = stats.completed_sessions_week + stats.interrupted_sessions_week
        return f"{round(100 * stats.completed_sessions_week / attempted)}%" if attempted else "—"

    def _refresh_settings(self) -> None:
        values = self.services.settings.all()
        table = self.query_one("#settings-table", DataTable)
        rows = tuple(
            (
                SETTING_LABELS.get(key, key.replace("_", " ").title()),
                "On" if value is True else "Off" if value is False else str(value),
            )
            for key, value in values.items()
        )
        if rows != self._settings_table_signature:
            self._settings_table_signature = rows
            table.clear()
            self._setting_row_map = list(values)
            for row in rows:
                table.add_row(*row)
        self.selected_setting_key = self.selected_setting_key or (
            self._setting_row_map[0] if self._setting_row_map else None
        )
        self.query_one("#settings-summary", Static).update(
            "\n".join(
                [
                    "SETTINGS",
                    "",
                    "Select a row and press e to change it.",
                    "On/off settings toggle immediately.",
                ]
            )
        )
        self.query_one("#settings-hints", Static).update(
            "\n".join(
                [
                    "FOCUS RECIPE",
                    "",
                    "50m work  ·  10m reset",
                    "25m long break every 4 cycles",
                    "Focus guard starts only when requested",
                    "",
                    "F2 switches light and dark instantly.",
                ]
            )
        )

    def _refresh_help(self) -> None:
        self.query_one("#help-pane", Static).update(
            "\n".join(
                [
                    f"{APP_NAME} Shortcuts",
                    "",
                    "g dashboard      t tasks          i statistics      , settings",
                    "a add task       e edit           d delete          x complete",
                    "/ search         f filter         s pomodoro        p pause/resume",
                    "m toggle focus   b blocked sites  ? help            q quit",
                    "F2 toggle light/dark theme",
                    "",
                    "Omarchy bar integration",
                    "Left click opens the TUI.",
                    "Right click toggles pomodoro.",
                    "Middle click toggles focus mode.",
                ]
            )
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._select_table_row(event.data_table)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._select_table_row(event.data_table)

    def _select_table_row(self, table: DataTable[Any]) -> None:
        cursor_row = max(0, table.cursor_row)
        if table.id in {"dashboard-tasks", "tasks-table"}:
            row_map = self._task_row_map.get(str(table.id), [])
            if cursor_row < len(row_map):
                self.selected_task_id = row_map[cursor_row]
                self._refresh_dashboard_now()
                self._update_task_detail("#task-detail")
        elif table.id == "focus-sites-table":
            if cursor_row < len(self._site_row_map):
                self.selected_focus_domain = self._site_row_map[cursor_row]
        elif table.id == "settings-table" and cursor_row < len(self._setting_row_map):
            self.selected_setting_key = self._setting_row_map[cursor_row]

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "task-search":
            if self._search_timer:
                self._search_timer.stop()
            self._apply_task_search(event.value)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "task-search" or event.value == self.filters.search:
            return
        if self._search_timer:
            self._search_timer.stop()
        self._search_timer = self.set_timer(0.2, lambda: self._apply_task_search(event.value))

    def _apply_task_search(self, value: str) -> None:
        self.filters.search = value.strip()
        self._refresh_tasks()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "start-session": self.action_toggle_pomodoro,
            "add-task": self.action_add_task,
            "focus-toggle": self.action_toggle_focus,
        }
        action = actions.get(event.button.id or "")
        if action:
            action()

    def show_view(self, view_id: str) -> None:
        tabs = self.query_one("#views", TabbedContent)
        tabs.active = view_id

    def action_show_dashboard(self) -> None:
        self.show_view("dashboard")

    def action_show_tasks(self) -> None:
        self.show_view("tasks")
        self.query_one("#task-search", Input).focus()

    def action_show_statistics(self) -> None:
        self.show_view("statistics")

    def action_show_settings(self) -> None:
        self.show_view("settings")

    def action_show_help(self) -> None:
        self.show_view("help")

    def action_toggle_theme(self) -> None:
        new_theme = DAYLIGHT_GOLD.name if self.theme == MIDNIGHT_GOLD.name else MIDNIGHT_GOLD.name
        self.theme = new_theme
        self.services.settings.set(THEME_SETTING_KEY, new_theme)
        label = "Light" if new_theme == DAYLIGHT_GOLD.name else "Dark"
        self.notify(f"Theme: {label}", timeout=2)

    def action_app_quit(self) -> None:
        self.exit()

    def action_add_task(self) -> None:
        self.push_screen(QuickAddTaskScreen(), self._handle_add_task)

    def _handle_add_task(self, result: str | None) -> None:
        if not isinstance(result, str) or not result.strip():
            return
        self.services.tasks.add_task(result.strip())
        self.show_view("tasks")
        self.refresh_data()

    def action_edit_selected(self) -> None:
        active = self.query_one("#views", TabbedContent).active
        if active == "settings":
            self._edit_selected_setting()
            return
        if active == "focus":
            self.action_show_blocked_sites()
            return
        task = self._get_task_by_selection()
        if not task:
            return
        self.push_screen(TaskEditorScreen(task=task), lambda result: self._handle_edit_task(task.id, result))

    def _handle_edit_task(self, task_id: int, result: TaskEditorResult | None) -> None:
        if not isinstance(result, TaskEditorResult) or not result.title:
            return
        self.services.tasks.update_task(
            task_id,
            title=result.title,
            description=result.description,
            priority=result.priority,
            tags=result.tags,
            estimated_minutes=result.estimate,
            due_at=result.due,
            clear_estimated_minutes=result.estimate is None,
            clear_due_at=result.due is None,
        )
        self.refresh_data()

    def _edit_selected_setting(self) -> None:
        if not self.selected_setting_key:
            return
        key = self.selected_setting_key
        if key == THEME_SETTING_KEY:
            self.action_toggle_theme()
            self.refresh_data()
            return
        current_value = self.services.settings.get(key)
        if isinstance(current_value, bool):
            self.services.settings.set(key, not current_value)
            self.notify(f"{SETTING_LABELS.get(key, key)}: {'On' if not current_value else 'Off'}", timeout=2)
            self.refresh_data()
            return
        self.push_screen(
            SettingEditScreen(SETTING_LABELS.get(key, key), str(current_value)),
            lambda result: self._handle_setting_edit(key, result),
        )

    def _handle_setting_edit(self, key: str, result: str | None) -> None:
        if not isinstance(result, str):
            return
        current = self.services.settings.get(key)
        value: Any = result
        if isinstance(current, int) and not isinstance(current, bool):
            if not result.isdigit() or int(result) < 1:
                self.notify(
                    "Enter a whole number greater than zero.", title="Setting not changed", severity="error"
                )
                return
            value = int(result)
        elif key == "default_view" and result not in {
            "dashboard",
            "tasks",
            "focus",
            "statistics",
            "settings",
            "help",
        }:
            self.notify("Use dashboard, tasks, focus, statistics, settings, or help.", severity="error")
            return
        elif key == "bar_output_mode" and result not in {"json", "plain"}:
            self.notify("Bar output must be json or plain.", severity="error")
            return
        self.services.settings.set(key, value)
        self.refresh_data()

    def action_delete_selected(self) -> None:
        task = self._get_task_by_selection()
        if not task:
            return
        self.push_screen(
            ConfirmScreen("Delete Task", f"Delete “{task.title}”? This cannot be undone."),
            lambda confirmed: self._handle_delete_confirm(task.id, confirmed),
        )

    def _handle_delete_confirm(self, task_id: int, confirmed: bool) -> None:
        if not confirmed:
            return
        self.services.tasks.delete_task(task_id)
        self.selected_task_id = None
        self.refresh_data()

    def action_complete_selected(self) -> None:
        task = self._get_task_by_selection()
        if not task:
            return
        self.services.tasks.complete_task(
            task.id,
            notifications_enabled=self.services.settings.get("notifications_enabled"),
        )
        self.refresh_data()

    def action_search_tasks(self) -> None:
        self.show_view("tasks")
        search = self.query_one("#task-search", Input)
        search.focus()
        search.action_end()

    def action_filter_tasks(self) -> None:
        self.push_screen(FilterScreen(self.filters), self._handle_filter_result)

    def _handle_filter_result(self, result: TaskFilters | None) -> None:
        if not isinstance(result, TaskFilters):
            return
        result.search = self.filters.search
        self.filters = result
        self.show_view("tasks")
        self.refresh_data()

    def action_toggle_pomodoro(self) -> None:
        snapshot = self.services.pomodoro.status()
        if snapshot.phase == SessionPhase.IDLE:
            task = self._get_task_by_selection()
            self.services.pomodoro.start(task_id=task.id if task else None)
        else:
            self.services.pomodoro.stop(reason="stopped from TUI")
        self.refresh_data()

    def action_pause_resume(self) -> None:
        snapshot = self.services.pomodoro.status()
        if snapshot.phase == SessionPhase.RUNNING:
            self.services.pomodoro.pause()
        elif snapshot.phase == SessionPhase.PAUSED:
            self.services.pomodoro.resume()
        self.refresh_data()

    def action_toggle_focus(self) -> None:
        from ..exceptions import FocusModeError

        try:
            with self.suspend():
                focus = self.services.focus.status()
                if focus.active:
                    self.services.focus.stop(force=False)
                else:
                    pomodoro = self.services.pomodoro.status()
                    minutes = None
                    if pomodoro.phase == SessionPhase.RUNNING and pomodoro.session_type == SessionType.WORK:
                        minutes = max(1, math.ceil(pomodoro.remaining_seconds / 60))
                    self.services.focus.start(minutes=minutes)
        except FocusModeError as exc:
            self.notify(str(exc), title="Focus Mode", severity="error")
        self.show_view("focus")
        self.refresh_data()

    def action_show_blocked_sites(self) -> None:
        self.show_view("focus")
        self.push_screen(
            BlockedSitesScreen(self.selected_focus_domain),
            lambda _: self.refresh_data(),
        )
