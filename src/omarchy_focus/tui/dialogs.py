"""Modal dialogs used by the Textual app."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Select, Static

from ..models import TaskFilters, TaskPriority, TaskStatus
from ..utils import parse_user_datetime


@dataclass(slots=True)
class TaskEditorResult:
    title: str
    description: str
    priority: str
    tags: str
    estimate: int | None
    due: str | None


class QuickAddTaskScreen(ModalScreen[str | None]):
    DEFAULT_CSS = """
    QuickAddTaskScreen {
        align: center middle;
    }

    #quick-add-task {
        width: 72;
        max-width: 95%;
        height: auto;
        background: $panel;
        color: $foreground;
        border: tall $primary;
        padding: 1 2;
    }

    #quick-add-task .dialog-title {
        color: $accent;
        text-style: bold;
        padding-bottom: 1;
    }

    #quick-add-task Input {
        margin-bottom: 1;
    }

    #quick-add-task .button-row {
        align: right middle;
        height: auto;
    }

    #quick-add-error {
        height: auto;
        color: $error;
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="quick-add-task"):
            yield Static("Add Task", classes="dialog-title")
            yield Input(placeholder="Write report, call client, pay bill…", id="quick-task-title")
            yield Static("", id="quick-add-error")
            with Horizontal(classes="button-row"):
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("Add", variant="primary", id="save")

    def on_mount(self) -> None:
        self.query_one("#quick-task-title", Input).focus()

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self._submit()

    def _submit(self) -> None:
        title = self.query_one("#quick-task-title", Input).value.strip()
        if not title:
            self.query_one("#quick-add-error", Static).update("Name the task before adding it.")
            return
        self.dismiss(title)


class TaskEditorScreen(ModalScreen[TaskEditorResult | None]):
    DEFAULT_CSS = """
    TaskEditorScreen {
        align: center middle;
    }

    #task-editor {
        width: 88;
        max-width: 95%;
        height: auto;
        background: $panel;
        color: $foreground;
        border: tall $primary;
        padding: 1 2;
    }

    #task-editor .dialog-title {
        color: $accent;
        text-style: bold;
        padding-bottom: 1;
    }

    #task-editor Input, #task-editor Select {
        margin-bottom: 1;
    }

    #task-editor .button-row {
        align: right middle;
        height: auto;
    }

    #task-editor-error {
        height: auto;
        color: $error;
        margin-bottom: 1;
    }
    """

    def __init__(self, *, task: Any | None = None) -> None:
        super().__init__()
        self.task_data = task

    def compose(self) -> ComposeResult:
        title = "Edit Task" if self.task_data else "New Task"
        with Vertical(id="task-editor"):
            yield Static(title, classes="dialog-title")
            yield Label("Title")
            yield Input(value=getattr(self.task_data, "title", ""), id="title")
            yield Label("Description / Notes")
            yield Input(value=getattr(self.task_data, "description", ""), id="description")
            yield Label("Priority")
            yield Select(
                [(item.value.title(), item.value) for item in TaskPriority],
                value=getattr(self.task_data, "priority", TaskPriority.MEDIUM).value,
                id="priority",
            )
            yield Label("Tags")
            yield Input(
                value=" ".join(getattr(self.task_data, "tags", ())),
                placeholder="#deep-work #client",
                id="tags",
            )
            yield Label("Estimated Minutes")
            yield Input(
                value=str(getattr(self.task_data, "estimated_minutes", "") or ""),
                placeholder="50",
                id="estimate",
            )
            yield Label("Due Date / Time")
            due_value = ""
            due_at = getattr(self.task_data, "due_at", None)
            if due_at:
                due_value = due_at.astimezone().strftime("%Y-%m-%d %H:%M")
            yield Input(value=due_value, placeholder="2026-04-20 14:30", id="due")
            yield Static("", id="task-editor-error")
            with Horizontal(classes="button-row"):
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("Save", variant="primary", id="save")

    def on_mount(self) -> None:
        self.query_one("#title", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self._submit()

    def _submit(self) -> None:
        title = self.query_one("#title", Input).value.strip()
        estimate_raw = self.query_one("#estimate", Input).value.strip()
        due = self.query_one("#due", Input).value.strip()
        error = self.query_one("#task-editor-error", Static)
        if not title:
            error.update("Task title is required.")
            self.query_one("#title", Input).focus()
            return
        if estimate_raw and (not estimate_raw.isdigit() or int(estimate_raw) < 1):
            error.update("Estimate must be a whole number greater than zero.")
            self.query_one("#estimate", Input).focus()
            return
        if due:
            try:
                parse_user_datetime(due)
            except ValueError:
                error.update("Use YYYY-MM-DD HH:MM or DD.MM.YYYY HH:MM for the due date.")
                self.query_one("#due", Input).focus()
                return
        estimate = int(estimate_raw) if estimate_raw else None
        self.dismiss(
            TaskEditorResult(
                title=title,
                description=self.query_one("#description", Input).value.strip(),
                priority=str(self.query_one("#priority", Select).value),
                tags=self.query_one("#tags", Input).value.strip(),
                estimate=estimate,
                due=due or None,
            )
        )


class FilterScreen(ModalScreen[TaskFilters | None]):
    DEFAULT_CSS = """
    FilterScreen {
        align: center middle;
    }

    #filter-dialog {
        width: 78;
        max-width: 95%;
        background: $panel;
        color: $foreground;
        border: solid $secondary;
        padding: 1 2;
    }
    """

    def __init__(self, current: TaskFilters) -> None:
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="filter-dialog"):
            yield Static("Filter Tasks", classes="dialog-title")
            yield Label("Status")
            yield Select(
                [("Any", "any")]
                + [(item.value.replace("_", " ").title(), item.value) for item in TaskStatus],
                value=self.current.status.value if self.current.status else "any",
                id="status",
            )
            yield Label("Priority")
            yield Select(
                [("Any", "any")] + [(item.value.title(), item.value) for item in TaskPriority],
                value=self.current.priority.value if self.current.priority else "any",
                id="priority",
            )
            yield Label("Sort")
            yield Select(
                [
                    ("Updated", "updated_desc"),
                    ("Due Date", "due_asc"),
                    ("Priority", "priority_desc"),
                    ("Title", "title_asc"),
                    ("Created", "created_desc"),
                    ("Status", "status"),
                ],
                value=self.current.sort_by,
                id="sort",
            )
            yield Checkbox("Today only", value=self.current.today, id="today")
            yield Checkbox("Completed view", value=self.current.completed, id="completed")
            yield Checkbox("Include archived", value=self.current.include_archived, id="archived")
            with Horizontal(classes="button-row"):
                yield Button("Cancel", id="cancel")
                yield Button("Apply", variant="primary", id="apply")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        status_value = self.query_one("#status", Select).value
        priority_value = self.query_one("#priority", Select).value
        self.dismiss(
            TaskFilters(
                search=self.current.search,
                status=TaskStatus(str(status_value)) if status_value != "any" else None,
                priority=TaskPriority(str(priority_value)) if priority_value != "any" else None,
                today=self.query_one("#today", Checkbox).value,
                completed=self.query_one("#completed", Checkbox).value,
                include_archived=self.query_one("#archived", Checkbox).value,
                sort_by=str(self.query_one("#sort", Select).value),
            )
        )


class ConfirmScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }

    #confirm-dialog {
        width: 64;
        max-width: 95%;
        background: $panel;
        color: $foreground;
        border: solid $error;
        padding: 1 2;
    }
    """

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.dialog_title = title
        self.body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self.dialog_title, classes="dialog-title")
            yield Static(self.body)
            with Horizontal(classes="button-row"):
                yield Button("Cancel", id="cancel")
                yield Button("Confirm", variant="error", id="confirm")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")


class BreakPromptScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    BreakPromptScreen {
        align: center middle;
    }

    #break-prompt-dialog {
        width: 74;
        max-width: 95%;
        background: $panel;
        color: $foreground;
        border: tall $primary;
        padding: 1 2;
    }

    #break-prompt-dialog .button-row {
        align: right middle;
        height: auto;
    }
    """

    def __init__(self, *, minutes: int, task_title: str | None = None) -> None:
        super().__init__()
        self.minutes = minutes
        self.task_title = task_title

    def compose(self) -> ComposeResult:
        task_suffix = f"\nTask: {self.task_title}" if self.task_title else ""
        with Vertical(id="break-prompt-dialog"):
            yield Static("Pomodoro Complete", classes="dialog-title")
            yield Static(f"Start a {self.minutes}-minute break?{task_suffix}\nThe timer begins immediately.")
            with Horizontal(classes="button-row"):
                yield Button("Skip", id="skip")
                yield Button(f"Start {self.minutes}m Break", variant="primary", id="start-break")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "start-break")


class SettingEditScreen(ModalScreen[str | None]):
    DEFAULT_CSS = """
    SettingEditScreen {
        align: center middle;
    }

    #setting-dialog {
        width: 72;
        max-width: 95%;
        background: $panel;
        color: $foreground;
        border: solid $secondary;
        padding: 1 2;
    }
    """

    def __init__(self, key: str, current: str) -> None:
        super().__init__()
        self.key = key
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="setting-dialog"):
            yield Static(f"Edit Setting: {self.key}", classes="dialog-title")
            yield Input(value=self.current, id="setting-value")
            with Horizontal(classes="button-row"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="primary", id="save")

    def on_mount(self) -> None:
        self.query_one("#setting-value", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            self.dismiss(self.query_one("#setting-value", Input).value.strip())


class BlockedSitesScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    BlockedSitesScreen {
        align: center middle;
    }

    #blocked-sites-dialog {
        width: 92;
        max-width: 95%;
        height: 30;
        background: $panel;
        color: $foreground;
        border: solid $secondary;
        padding: 1 2;
    }

    #blocked-sites-dialog DataTable {
        height: 1fr;
        margin-bottom: 1;
    }

    #blocked-sites-dialog .button-row {
        align: right middle;
    }
    """

    def __init__(self, selected_domain: str | None = None) -> None:
        super().__init__()
        self.selected_domain = selected_domain

    def compose(self) -> ComposeResult:
        with Vertical(id="blocked-sites-dialog"):
            yield Static("Blocked Sites", classes="dialog-title")
            yield DataTable(id="blocked-sites-table")
            yield Input(placeholder="new-domain.com", id="site-input")
            yield Checkbox("Enabled", value=True, id="site-enabled")
            with Horizontal(classes="button-row"):
                yield Button("New", id="new")
                yield Button("Toggle Enabled", id="toggle")
                yield Button("Save", variant="primary", id="save")
                yield Button("Remove Selected", id="remove")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        table = self.query_one("#blocked-sites-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Domain", "Enabled", "Source")
        self.refresh_table()
        self.query_one("#site-input", Input).focus()

    def refresh_table(self) -> None:
        from .app import OmarchyFocusApp

        app = self.app
        assert isinstance(app, OmarchyFocusApp)
        table = self.query_one("#blocked-sites-table", DataTable)
        table.clear()
        self._rows: list[tuple[str, bool, str]] = []
        for domain, enabled, source in app.services.focus.list_sites():
            self._rows.append((domain, enabled, source))
            table.add_row(domain, "yes" if enabled else "no", source)
        if self.selected_domain:
            for index, (domain, _, _) in enumerate(self._rows):
                if domain == self.selected_domain:
                    table.move_cursor(row=index)
                    break

    def _load_selected(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self._rows):
            return
        domain, enabled, _ = self._rows[row_index]
        self.selected_domain = domain
        self.query_one("#site-input", Input).value = domain
        self.query_one("#site-enabled", Checkbox).value = enabled

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "blocked-sites-table":
            return
        self._load_selected(max(0, event.data_table.cursor_row))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        from ..exceptions import FocusModeError
        from .app import OmarchyFocusApp

        app = self.app
        assert isinstance(app, OmarchyFocusApp)
        input_widget = self.query_one("#site-input", Input)
        checkbox = self.query_one("#site-enabled", Checkbox)
        if event.button.id == "close":
            self.dismiss(False)
            return
        if event.button.id == "new":
            self.selected_domain = None
            input_widget.value = ""
            checkbox.value = True
            input_widget.focus()
            return

        table = self.query_one("#blocked-sites-table", DataTable)
        cursor_row = max(0, table.cursor_row)
        selected = self._rows[cursor_row] if self._rows and cursor_row < len(self._rows) else None

        if event.button.id == "save":
            domain = input_widget.value.strip()
            if not domain:
                return
            try:
                with app.suspend():
                    if self.selected_domain:
                        self.selected_domain = app.services.focus.update_site(
                            self.selected_domain,
                            new_domain=domain,
                            enabled=checkbox.value,
                        )
                    else:
                        app.services.focus.add_site(domain, enabled=checkbox.value)
                        self.selected_domain = domain
            except FocusModeError as exc:
                app.notify(str(exc), title="Blocked Sites", severity="error")
                return
            self.refresh_table()
            app.refresh_data()
            return

        if event.button.id == "toggle":
            if selected:
                domain, enabled, _ = selected
                try:
                    with app.suspend():
                        app.services.focus.toggle_site(domain, not enabled)
                except FocusModeError as exc:
                    app.notify(str(exc), title="Blocked Sites", severity="error")
                    return
                self.selected_domain = domain
                checkbox.value = not enabled
                self.refresh_table()
                app.refresh_data()
            return

        if event.button.id == "remove" and selected:
            try:
                with app.suspend():
                    app.services.focus.remove_site(selected[0])
            except FocusModeError as exc:
                app.notify(str(exc), title="Blocked Sites", severity="error")
                return
            self.selected_domain = None
            input_widget.value = ""
            checkbox.value = True
            self.refresh_table()
            app.refresh_data()
