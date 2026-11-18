"""Outbound ports for the task context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

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


class FundReservationStore(ABC):
    """Persistence port for per-task live trading fund reservations."""

    @abstractmethod
    async def reserve(
        self,
        *,
        account_key: str,
        exchange: str,
        credential_id: int | None,
        user_id: int | None,
        task_id: int,
        asset: str,
        amount: float,
        capacity: float,
        reason: str,
        balance: float | None = None,
        max_borrowable: float | None = None,
        borrow_limit: float | None = None,
        operable_capacity: float | None = None,
    ) -> Any: ...

    @abstractmethod
    async def active_reserved_amount(self, account_key: str, asset: str) -> float: ...

    @abstractmethod
    async def remaining_for_task(self, task_id: int, asset: str) -> float | None: ...

    @abstractmethod
    async def mark_spent(self, task_id: int, asset: str, amount: float) -> Any: ...

    @abstractmethod
    async def release_task(self, task_id: int, *, reason: str) -> int: ...

    @abstractmethod
    async def get_active_for_task(self, task_id: int, asset: str) -> Any: ...

    @abstractmethod
    async def release_inactive_tasks(self, running_task_ids: set[int], *, reason: str) -> int: ...


@runtime_checkable
class TaskRunner(Protocol):
    """Port for executing a configured task."""

    async def run(self, cfg: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class TaskEventPublisher(Protocol):
    """Port for publishing live task dashboard/runtime events."""

    async def publish(self, event: Any) -> Any: ...
