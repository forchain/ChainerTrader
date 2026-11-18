"""Outbound ports for the task context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from trader.core.task.domain import TaskState


class TaskRepository(ABC):
    @abstractmethod
    async def add_tasks(self, tasks: list[TaskState]) -> int: ...

    @abstractmethod
    async def del_task(self, id: int) -> bool: ...

    @abstractmethod
    async def get_task(self, id: int) -> TaskState | None: ...

    @abstractmethod
    async def get_task_for_user(self, id: int, user_id: int) -> TaskState | None: ...

    @abstractmethod
    async def get_all_tasks(self) -> list[TaskState]: ...

    @abstractmethod
    async def get_all_tasks_for_user(self, user_id: int) -> list[TaskState]: ...


class TaskQuery(Protocol):
    """Read side used by task query use cases; implemented by the task runtime and repositories."""

    async def get_task_state(self, id: int, user_id: int | None = None) -> TaskState | None: ...

    async def get_all_task_state(self, user_id: int | None = None) -> list[TaskState]: ...
