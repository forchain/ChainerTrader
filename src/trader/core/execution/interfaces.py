from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from trader.core.execution.domain import ExecutionResult, GatewayCapabilities, OrderIntent, ReconcileRequest, ReconcileResult, RiskIntent
from trader.core.execution.state import ExecutionStateRecord, ExecutionStateReservation


class ExecutionGateway(ABC):
    @property
    def capabilities(self) -> GatewayCapabilities | None:
        return None

    @abstractmethod
    def open_position(self, intent: OrderIntent) -> ExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def place_protection(self, intent: RiskIntent) -> ExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def replace_protection(self, intent: RiskIntent) -> ExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def close_position(self, intent: OrderIntent) -> ExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, intent: OrderIntent) -> ExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def reconcile(self, request: ReconcileRequest) -> ReconcileResult:
        raise NotImplementedError


@runtime_checkable
class ExecutionGatewayFactory(Protocol):
    """Port for constructing an execution gateway for a mode and exchange."""

    def __call__(self, mode: str, exchange: Any) -> ExecutionGateway: ...


class ExecutionStateStore(Protocol):
    async def reserve(self, record: ExecutionStateRecord) -> ExecutionStateReservation:
        ...

    async def save(self, record: ExecutionStateRecord) -> ExecutionStateRecord:
        ...

    async def get_by_idempotency_key(self, idempotency_key: str) -> ExecutionStateRecord | None:
        ...

    async def list_open_by_symbol(self, symbol: str) -> list[ExecutionStateRecord]:
        ...

    async def list_open_by_task(self, task_id: int) -> list[ExecutionStateRecord]:
        ...
