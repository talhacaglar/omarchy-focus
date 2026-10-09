"""Task service."""

from __future__ import annotations

import json
from sqlite3 import Row

from ..database import Database
from ..exceptions import TaskNotFoundError
from ..models import Task, TaskFilters, TaskPriority, TaskStatus
from ..notifications import notify
from ..utils import coerce_tags, parse_dt, parse_user_datetime, to_iso, utc_now


class TaskService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _row_to_task(self, row: Row) -> Task:
        return Task(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            priority=TaskPriority(row["priority"]),
            status=TaskStatus(row["status"]),
            tags=tuple(json.loads(row["tags_json"])),
            estimated_minutes=row["estimated_minutes"],
            due_at=parse_dt(row["due_at"]),
            created_at=parse_dt(row["created_at"]),
            updated_at=parse_dt(row["updated_at"]),
            completed_at=parse_dt(row["completed_at"]),
            archived_at=parse_dt(row["archived_at"]),
        )

    def add_task(
        self,
        title: str,
        *,
        description: str = "",
        priority: str = "medium",
        tags: str | list[str] | None = None,
        estimated_minutes: int | None = None,
        due_at: str | None = None,
        status: str = "pending",
    ) -> Task:
        if not title.strip():
            raise ValueError("Task title cannot be empty")
        now = utc_now()
        due = parse_user_datetime(due_at) if isinstance(due_at, str) else due_at
        tags_json = json.dumps(coerce_tags(tags))
        with self.db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tasks (
                    title, description, priority, status, tags_json, estimated_minutes,
                    due_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title.strip(),
                    description.strip(),
                    TaskPriority(priority).value,
                    TaskStatus(status).value,
                    tags_json,
                    estimated_minutes,
                    to_iso(due),
                    to_iso(now),
                    to_iso(now),
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Task insert did not return an id")
            task_id = int(cursor.lastrowid)
        return self.get_task(task_id)

    def get_task(self, task_id: int) -> Task:
        row = self.db.fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if not row:
            raise TaskNotFoundError(f"Task {task_id} not found")
        return self._row_to_task(row)

    def list_tasks(self, filters: TaskFilters | None = None) -> list[Task]:
        filters = filters or TaskFilters()
        clauses: list[str] = []
        params: list[object] = []

        if filters.completed:
            clauses.append("status = 'done'")
        elif filters.status:
            clauses.append("status = ?")
            params.append(filters.status.value)
        elif not filters.include_archived:
            clauses.append("status != 'archived'")

        if filters.priority:
            clauses.append("priority = ?")
            params.append(filters.priority.value)

        if filters.today:
            clauses.append(
                """
                (
                    status = 'in_progress'
                    OR (due_at IS NOT NULL AND date(due_at, 'localtime') <= date('now', 'localtime'))
                )
                """
            )

        if filters.search:
            clauses.append("(title LIKE ? OR description LIKE ? OR tags_json LIKE ?)")
            token = f"%{filters.search.strip()}%"
            params.extend([token, token, token])

        if filters.tag:
            clauses.append("tags_json LIKE ?")
            params.append(f'%"{filters.tag.lower()}"%')

        order_by = {
            "created_desc": "created_at DESC",
            "updated_desc": "updated_at DESC",
            "due_asc": "CASE WHEN due_at IS NULL THEN 1 ELSE 0 END, due_at ASC",
            "priority_desc": """
                CASE priority
                    WHEN 'high' THEN 0
                    WHEN 'medium' THEN 1
                    ELSE 2
                END, updated_at DESC
            """,
            "title_asc": "title COLLATE NOCASE ASC",
            "status": "status ASC, updated_at DESC",
        }.get(filters.sort_by, "updated_at DESC")

        sql = "SELECT * FROM tasks"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += f" ORDER BY {order_by}"
        return [self._row_to_task(row) for row in self.db.fetchall(sql, tuple(params))]

    def update_task(
        self,
        task_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
        priority: str | None = None,
        tags: str | list[str] | None = None,
        estimated_minutes: int | None = None,
        due_at: str | None = None,
        status: str | None = None,
        clear_estimated_minutes: bool = False,
        clear_due_at: bool = False,
    ) -> Task:
        task = self.get_task(task_id)
        estimate = (
            None
            if clear_estimated_minutes
            else estimated_minutes
            if estimated_minutes is not None
            else task.estimated_minutes
        )
        due = None if clear_due_at else parse_user_datetime(due_at) if due_at is not None else task.due_at
        if title is not None and not title.strip():
            raise ValueError("Task title cannot be empty")
        fields = {
            "title": title.strip() if title is not None else task.title,
            "description": description.strip() if description is not None else task.description,
            "priority": TaskPriority(priority or task.priority).value,
            "status": TaskStatus(status or task.status).value,
            "tags_json": json.dumps(coerce_tags(tags) if tags is not None else list(task.tags)),
            "estimated_minutes": estimate,
            "due_at": to_iso(due),
            "updated_at": to_iso(utc_now()),
        }
        completed_at = task.completed_at
        archived_at = task.archived_at
        if fields["status"] == TaskStatus.DONE.value and not completed_at:
            completed_at = utc_now()
        elif fields["status"] != TaskStatus.DONE.value:
            completed_at = None
        if fields["status"] == TaskStatus.ARCHIVED.value and not archived_at:
            archived_at = utc_now()
        elif fields["status"] != TaskStatus.ARCHIVED.value:
            archived_at = None
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE tasks SET
                    title = :title,
                    description = :description,
                    priority = :priority,
                    status = :status,
                    tags_json = :tags_json,
                    estimated_minutes = :estimated_minutes,
                    due_at = :due_at,
                    updated_at = :updated_at,
                    completed_at = :completed_at,
                    archived_at = :archived_at
                WHERE id = :id
                """,
                {
                    **fields,
                    "completed_at": to_iso(completed_at),
                    "archived_at": to_iso(archived_at),
                    "id": task_id,
                },
            )
        return self.get_task(task_id)

    def complete_task(self, task_id: int, *, notifications_enabled: bool = True) -> Task:
        task = self.update_task(task_id, status=TaskStatus.DONE.value)
        notify("Task complete", task.title, enabled=notifications_enabled)
        return task

    def delete_task(self, task_id: int) -> None:
        self.get_task(task_id)
        self.db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def count_pending(self) -> int:
        row = self.db.fetchone(
            "SELECT COUNT(*) AS count FROM tasks WHERE status IN ('pending', 'in_progress')"
        )
        return int(row["count"]) if row else 0

    def count_done_today(self) -> int:
        row = self.db.fetchone(
            """
            SELECT COUNT(*) AS count
            FROM tasks
            WHERE completed_at IS NOT NULL
              AND date(completed_at, 'localtime') = date('now', 'localtime')
            """
        )
        return int(row["count"]) if row else 0

    def get_in_progress(self) -> Task | None:
        row = self.db.fetchone(
            """
            SELECT * FROM tasks
            WHERE status = 'in_progress'
            ORDER BY updated_at DESC
            LIMIT 1
            """
        )
        return self._row_to_task(row) if row else None

    def list_open(self, limit: int = 5) -> list[Task]:
        """Open tasks in the order the dashboard suggests working on them."""
        rows = self.db.fetchall(
            """
            SELECT * FROM tasks
            WHERE status IN ('pending', 'in_progress')
            ORDER BY
                CASE status WHEN 'in_progress' THEN 0 ELSE 1 END,
                CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_task(row) for row in rows]

    def get_next_focus_candidate(self) -> Task | None:
        candidates = self.list_open(limit=1)
        return candidates[0] if candidates else None
