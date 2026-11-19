"""Task query use cases: ownership scope, pagination, and detail access."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from trader.core.task.domain import TaskState
from trader.core.task.exceptions import TaskNotFound, TaskOwnership
from trader.core.task.interfaces import TaskQuery

T = TypeVar("T")


@dataclass(frozen=True)
class TaskScope:
    """Ownership scope: ``None`` means every task, otherwise only that user's tasks."""

    user_id: int | None = None

    @classmethod
    def all(cls) -> "TaskScope":
        return cls()

    @classmethod
    def for_user(cls, user_id: int) -> "TaskScope":
        return cls(user_id)

    @classmethod
    def for_actor(cls, user) -> "TaskScope":
        """Admins (and anonymous callers) see every task; regular users see their own."""
        if user is None or getattr(user, "is_admin", False):
            return cls.all()
        return cls.for_user(user.id)


@dataclass(frozen=True)
class TaskPage(Generic[T]):
    items: list[T]
    total: int
    page: int
    per_page: int
    total_pages: int


def paginate(items: list[T], page: int = 1, per_page: int | None = None, *, max_per_page: int | None = None) -> TaskPage[T]:
    total = len(items)
    safe_page = max(1, int(page or 1))
    if per_page is None:
        return TaskPage(items=list(items), total=total, page=1, per_page=total, total_pages=1)

    safe_per_page = max(1, int(per_page))
    if max_per_page is not None:
        safe_per_page = min(max_per_page, safe_per_page)
    total_pages = max(1, (total + safe_per_page - 1) // safe_per_page)
    safe_page = min(safe_page, total_pages)
    start = (safe_page - 1) * safe_per_page
    return TaskPage(
        items=list(items[start : start + safe_per_page]),
        total=total,
        page=safe_page,
        per_page=safe_per_page,
        total_pages=total_pages,
    )


def _task_sort_key(state: TaskState) -> str:
    return str(state.to_dict().get("start_time", ""))


class ListTasks:
    def __init__(self, tasks: TaskQuery):
        self.tasks = tasks

    async def execute(self, scope: TaskScope = TaskScope.all(), *, page: int = 1, per_page: int | None = None) -> TaskPage[TaskState]:
        states = await self.tasks.get_all_task_state(user_id=scope.user_id)
        states = sorted(states, key=_task_sort_key, reverse=True)
        return paginate(states, page=page, per_page=per_page)


class GetTask:
    def __init__(self, tasks: TaskQuery):
        self.tasks = tasks

    async def execute(self, task_id: int, scope: TaskScope = TaskScope.all()) -> TaskState:
        state = await self.tasks.get_task_state(task_id)
        if state is None:
            raise TaskNotFound(task_id)
        if scope.user_id is not None and getattr(state, "user_id", None) != scope.user_id:
            raise TaskOwnership(task_id, scope.user_id)
        return state
