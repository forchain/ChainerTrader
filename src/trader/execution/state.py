from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from trader.execution.models import ExecutionStatus, GatewayMode, OrderIntent, RiskIntent


def _normalize_gateway(value: GatewayMode | str) -> GatewayMode:
    if isinstance(value, GatewayMode):
        return value
    return GatewayMode(str(value))


def _normalize_status(value: ExecutionStatus | str) -> ExecutionStatus:
    if isinstance(value, ExecutionStatus):
        return value
    return ExecutionStatus(str(value))


@dataclass(frozen=True)
class ExecutionStateRecord:
    idempotency_key: str
    intent_id: str
    operation_id: str
    gateway: GatewayMode | str
    staged_execution_mode: str
    symbol: str
    order_role: str
    status: ExecutionStatus | str
    trade_id: str | None = None
    exchange_order_id: str | None = None
    protection_id: str | None = None
    quantity: float = 0.0
    price: float | None = None
    stop_price: float | None = None
    take_profit_price: float | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0
    updated_at: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "gateway", _normalize_gateway(self.gateway))
        object.__setattr__(self, "status", _normalize_status(self.status))
        if not self.idempotency_key:
            raise ValueError("idempotency_key is required")
        if not self.intent_id:
            raise ValueError("intent_id is required")
        if not self.operation_id:
            raise ValueError("operation_id is required")
        if not self.symbol:
            raise ValueError("symbol is required")
        if not self.order_role:
            raise ValueError("order_role is required")

    @classmethod
    def from_order_intent(
        cls,
        intent: OrderIntent,
        *,
        gateway: GatewayMode | str,
        staged_execution_mode: str,
        status: ExecutionStatus | str,
        exchange_order_id: str | None = None,
        timestamp: int = 0,
    ) -> "ExecutionStateRecord":
        return cls(
            idempotency_key=intent.idempotency_key,
            intent_id=intent.intent_id,
            operation_id=intent.operation_id,
            gateway=gateway,
            staged_execution_mode=staged_execution_mode,
            symbol=intent.symbol,
            trade_id=intent.trade_id,
            order_role=intent.intent_type.value,
            status=status,
            exchange_order_id=exchange_order_id,
            quantity=float(intent.quantity or 0.0),
            price=intent.price,
            raw_payload=intent.to_dict(),
            created_at=timestamp,
            updated_at=timestamp,
        )

    @classmethod
    def from_risk_intent(
        cls,
        intent: RiskIntent,
        *,
        gateway: GatewayMode | str,
        staged_execution_mode: str,
        status: ExecutionStatus | str,
        exchange_order_id: str | None = None,
        protection_id: str | None = None,
        timestamp: int = 0,
    ) -> "ExecutionStateRecord":
        return cls(
            idempotency_key=intent.idempotency_key,
            intent_id=intent.intent_id,
            operation_id=intent.operation_id,
            gateway=gateway,
            staged_execution_mode=staged_execution_mode,
            symbol=intent.symbol,
            trade_id=intent.trade_id,
            order_role=intent.protection_type.value,
            status=status,
            exchange_order_id=exchange_order_id,
            protection_id=protection_id,
            quantity=float(intent.quantity or 0.0),
            stop_price=intent.stop_price,
            take_profit_price=intent.take_profit_price,
            raw_payload=intent.to_dict(),
            created_at=timestamp,
            updated_at=timestamp,
        )

    def with_updates(self, **changes) -> "ExecutionStateRecord":
        return replace(self, **changes)


@dataclass(frozen=True)
class ExecutionStateReservation:
    record: ExecutionStateRecord
    created: bool


class ExecutionStateStore(Protocol):
    async def reserve(self, record: ExecutionStateRecord) -> ExecutionStateReservation:
        ...

    async def save(self, record: ExecutionStateRecord) -> ExecutionStateRecord:
        ...

    async def get_by_idempotency_key(self, idempotency_key: str) -> ExecutionStateRecord | None:
        ...

    async def list_open_by_symbol(self, symbol: str) -> list[ExecutionStateRecord]:
        ...
