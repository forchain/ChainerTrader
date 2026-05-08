from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class _StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class GatewayMode(_StrEnum):
    NOTIFICATION_ONLY = "notification_only"
    BACKTRADER = "backtrader"
    BINANCE_LIVE = "binance_live"


class ExecutionSide(_StrEnum):
    LONG = "long"
    SHORT = "short"


class OrderIntentType(_StrEnum):
    ENTRY = "entry"
    CLOSE = "close"
    CANCEL = "cancel"


class ProtectionIntentType(_StrEnum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    BRACKET = "bracket"
    REPLACE_STOP = "replace_stop"
    CANCEL = "cancel"


class RiskIntentAction(_StrEnum):
    PLACE_PROTECTION = "place_protection"
    REPLACE_PROTECTION = "replace_protection"
    CANCEL_PROTECTION = "cancel_protection"


class ExecutionStatus(_StrEnum):
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    SKIPPED = "skipped"
    FAILED = "failed"


class ExecutionReason(_StrEnum):
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    VALIDATION_ERROR = "validation_error"
    MODE_CONFLICT = "mode_conflict"
    DUPLICATE_INTENT = "duplicate_intent"
    PROTECTION_MISSING = "protection_missing"
    NATIVE_PROTECTION_UNVERIFIED = "native_protection_unverified"
    GATEWAY_REJECTED = "gateway_rejected"


class ExecutionEventType(_StrEnum):
    ORDER_SUBMITTED = "order_submitted"
    ORDER_ACCEPTED = "order_accepted"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELED = "order_canceled"
    ORDER_REJECTED = "order_rejected"
    PROTECTION_ARMED = "protection_armed"
    PROTECTION_TRIGGERED = "protection_triggered"
    PROTECTION_REPLACED = "protection_replaced"
    PROTECTION_MISSING = "protection_missing"
    RECONCILE_GAP_DETECTED = "reconcile_gap_detected"


class GatewayCapability(_StrEnum):
    MARKET_ENTRY = "market_entry"
    MARKET_CLOSE = "market_close"
    PROTECTIVE_STOP = "protective_stop"
    TAKE_PROFIT_LIMIT = "take_profit_limit"
    OCO_PROTECTION = "oco_protection"
    BREAKEVEN_REPLACEMENT = "breakeven_replacement"
    CANCEL_ORDER = "cancel_order"
    RECONCILE = "reconcile"


def _enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _normalize_enum(enum_type, value):
    if isinstance(value, enum_type):
        return value
    return enum_type(str(value))


def _require_text(value: str | None, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _require_positive(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    number = float(value)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    operation_id: str
    symbol: str
    side: ExecutionSide | str
    intent_type: OrderIntentType | str
    quantity: float | None = None
    notional: float | None = None
    price: float | None = None
    trade_id: str | None = None
    signal_event_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent_id", _require_text(self.intent_id, "intent_id"))
        object.__setattr__(self, "operation_id", _require_text(self.operation_id, "operation_id"))
        object.__setattr__(self, "symbol", _require_text(self.symbol, "symbol"))
        object.__setattr__(self, "side", _normalize_enum(ExecutionSide, self.side))
        object.__setattr__(self, "intent_type", _normalize_enum(OrderIntentType, self.intent_type))
        object.__setattr__(self, "quantity", _require_positive(self.quantity, "quantity"))
        object.__setattr__(self, "notional", _require_positive(self.notional, "notional"))
        object.__setattr__(self, "price", _require_positive(self.price, "price"))
        if self.intent_type in (OrderIntentType.ENTRY, OrderIntentType.CLOSE) and self.quantity is None and self.notional is None:
            raise ValueError("quantity or notional is required")

    @classmethod
    def entry(
        cls,
        *,
        intent_id: str,
        operation_id: str,
        symbol: str,
        side: ExecutionSide | str,
        quantity: float | None = None,
        notional: float | None = None,
        price: float | None = None,
        trade_id: str | None = None,
        signal_event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "OrderIntent":
        return cls(
            intent_id=intent_id,
            operation_id=operation_id,
            symbol=symbol,
            side=side,
            intent_type=OrderIntentType.ENTRY,
            quantity=quantity,
            notional=notional,
            price=price,
            trade_id=trade_id,
            signal_event_id=signal_event_id,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def close(
        cls,
        *,
        intent_id: str,
        operation_id: str,
        symbol: str,
        side: ExecutionSide | str,
        quantity: float | None = None,
        notional: float | None = None,
        price: float | None = None,
        trade_id: str | None = None,
        signal_event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "OrderIntent":
        return cls(
            intent_id=intent_id,
            operation_id=operation_id,
            symbol=symbol,
            side=side,
            intent_type=OrderIntentType.CLOSE,
            quantity=quantity,
            notional=notional,
            price=price,
            trade_id=trade_id,
            signal_event_id=signal_event_id,
            metadata=dict(metadata or {}),
        )

    @property
    def idempotency_key(self) -> str:
        return f"{self.intent_id}:{self.operation_id}:{self.intent_type.value}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "operation_id": self.operation_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "intent_type": self.intent_type.value,
            "quantity": self.quantity,
            "notional": self.notional,
            "price": self.price,
            "trade_id": self.trade_id,
            "signal_event_id": self.signal_event_id,
            "metadata": dict(self.metadata),
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True)
class RiskIntent:
    intent_id: str
    operation_id: str
    symbol: str
    side: ExecutionSide | str
    protection_type: ProtectionIntentType | str
    action: RiskIntentAction | str
    trade_id: str
    quantity: float
    stop_price: float | None = None
    take_profit_price: float | None = None
    replacement_of_order_id: str | None = None
    signal_event_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent_id", _require_text(self.intent_id, "intent_id"))
        object.__setattr__(self, "operation_id", _require_text(self.operation_id, "operation_id"))
        object.__setattr__(self, "symbol", _require_text(self.symbol, "symbol"))
        object.__setattr__(self, "trade_id", _require_text(self.trade_id, "trade_id"))
        object.__setattr__(self, "side", _normalize_enum(ExecutionSide, self.side))
        object.__setattr__(self, "protection_type", _normalize_enum(ProtectionIntentType, self.protection_type))
        object.__setattr__(self, "action", _normalize_enum(RiskIntentAction, self.action))
        object.__setattr__(self, "quantity", _require_positive(self.quantity, "quantity"))
        object.__setattr__(self, "stop_price", _require_positive(self.stop_price, "stop_price"))
        object.__setattr__(self, "take_profit_price", _require_positive(self.take_profit_price, "take_profit_price"))
        if self.action == RiskIntentAction.PLACE_PROTECTION and self.stop_price is None and self.take_profit_price is None:
            raise ValueError("stop_price or take_profit_price is required")
        if self.action == RiskIntentAction.REPLACE_PROTECTION and self.stop_price is None:
            raise ValueError("stop_price is required for replacement")

    @classmethod
    def place_protection(
        cls,
        *,
        intent_id: str,
        operation_id: str,
        symbol: str,
        side: ExecutionSide | str,
        trade_id: str,
        quantity: float,
        stop_price: float | None = None,
        take_profit_price: float | None = None,
        signal_event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "RiskIntent":
        if stop_price is not None and take_profit_price is not None:
            protection_type = ProtectionIntentType.BRACKET
        elif stop_price is not None:
            protection_type = ProtectionIntentType.STOP_LOSS
        else:
            protection_type = ProtectionIntentType.TAKE_PROFIT
        return cls(
            intent_id=intent_id,
            operation_id=operation_id,
            symbol=symbol,
            side=side,
            protection_type=protection_type,
            action=RiskIntentAction.PLACE_PROTECTION,
            trade_id=trade_id,
            quantity=quantity,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            signal_event_id=signal_event_id,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def replace_stop(
        cls,
        *,
        intent_id: str,
        operation_id: str,
        symbol: str,
        side: ExecutionSide | str,
        trade_id: str,
        quantity: float,
        stop_price: float,
        replacement_of_order_id: str | None = None,
        signal_event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "RiskIntent":
        return cls(
            intent_id=intent_id,
            operation_id=operation_id,
            symbol=symbol,
            side=side,
            protection_type=ProtectionIntentType.REPLACE_STOP,
            action=RiskIntentAction.REPLACE_PROTECTION,
            trade_id=trade_id,
            quantity=quantity,
            stop_price=stop_price,
            replacement_of_order_id=replacement_of_order_id,
            signal_event_id=signal_event_id,
            metadata=dict(metadata or {}),
        )

    @property
    def idempotency_key(self) -> str:
        return f"{self.intent_id}:{self.operation_id}:{self.action.value}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "operation_id": self.operation_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "protection_type": self.protection_type.value,
            "action": self.action.value,
            "trade_id": self.trade_id,
            "quantity": self.quantity,
            "stop_price": self.stop_price,
            "take_profit_price": self.take_profit_price,
            "replacement_of_order_id": self.replacement_of_order_id,
            "signal_event_id": self.signal_event_id,
            "metadata": dict(self.metadata),
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True)
class OrderView:
    order_id: str
    symbol: str
    status: ExecutionStatus | str
    role: str
    quantity: float
    price: float | None = None
    intent_id: str | None = None
    trade_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _normalize_enum(ExecutionStatus, self.status))


@dataclass(frozen=True)
class ProtectionOrderView:
    protection_id: str
    symbol: str
    protection_type: ProtectionIntentType | str
    status: ExecutionStatus | str
    quantity: float
    stop_price: float | None = None
    take_profit_price: float | None = None
    exchange_order_ids: tuple[str, ...] = ()
    intent_id: str | None = None
    trade_id: str | None = None
    native: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "protection_type", _normalize_enum(ProtectionIntentType, self.protection_type))
        object.__setattr__(self, "status", _normalize_enum(ExecutionStatus, self.status))


@dataclass(frozen=True)
class PositionView:
    symbol: str
    side: ExecutionSide | str
    quantity: float
    entry_price: float | None = None
    trade_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", _normalize_enum(ExecutionSide, self.side))


@dataclass(frozen=True)
class ExecutionEvent:
    event_type: ExecutionEventType | str
    gateway: GatewayMode | str
    staged_execution_mode: str
    intent_id: str
    operation_id: str
    symbol: str
    order_id: str | None = None
    trade_id: str | None = None
    status: ExecutionStatus | str | None = None
    reason: ExecutionReason | str | None = None
    quantity: float | None = None
    price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_type", _normalize_enum(ExecutionEventType, self.event_type))
        object.__setattr__(self, "gateway", _normalize_enum(GatewayMode, self.gateway))
        if self.status is not None:
            object.__setattr__(self, "status", _normalize_enum(ExecutionStatus, self.status))
        if self.reason is not None:
            object.__setattr__(self, "reason", _normalize_enum(ExecutionReason, self.reason))

    @classmethod
    def order_accepted(
        cls,
        *,
        gateway: GatewayMode | str,
        staged_execution_mode: str,
        intent_id: str,
        operation_id: str,
        symbol: str,
        order_id: str,
        trade_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ExecutionEvent":
        return cls(
            event_type=ExecutionEventType.ORDER_ACCEPTED,
            gateway=gateway,
            staged_execution_mode=staged_execution_mode,
            intent_id=intent_id,
            operation_id=operation_id,
            symbol=symbol,
            order_id=order_id,
            trade_id=trade_id,
            status=ExecutionStatus.ACCEPTED,
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "gateway": self.gateway.value,
            "staged_execution_mode": self.staged_execution_mode,
            "intent_id": self.intent_id,
            "operation_id": self.operation_id,
            "symbol": self.symbol,
            "order_id": self.order_id,
            "trade_id": self.trade_id,
            "status": _enum_value(self.status),
            "reason": _enum_value(self.reason),
            "quantity": self.quantity,
            "price": self.price,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ExecutionResult:
    intent_id: str
    operation_id: str
    status: ExecutionStatus | str
    reason: ExecutionReason | str | None = None
    gateway_order_id: str | None = None
    capability: GatewayCapability | str | None = None
    events: list[ExecutionEvent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _normalize_enum(ExecutionStatus, self.status))
        if self.reason is not None:
            object.__setattr__(self, "reason", _normalize_enum(ExecutionReason, self.reason))
        if self.capability is not None:
            object.__setattr__(self, "capability", _normalize_enum(GatewayCapability, self.capability))

    @classmethod
    def from_accepted(
        cls,
        *,
        intent_id: str,
        operation_id: str,
        status: ExecutionStatus | str,
        events: list[ExecutionEvent] | None = None,
        gateway_order_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ExecutionResult":
        return cls(
            intent_id=intent_id,
            operation_id=operation_id,
            status=status,
            events=list(events or []),
            gateway_order_id=gateway_order_id,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def unsupported(
        cls,
        *,
        intent_id: str,
        operation_id: str,
        capability: GatewayCapability | str,
        gateway: GatewayMode | str,
    ) -> "ExecutionResult":
        return cls(
            intent_id=intent_id,
            operation_id=operation_id,
            status=ExecutionStatus.REJECTED,
            reason=ExecutionReason.UNSUPPORTED_CAPABILITY,
            capability=capability,
            metadata={"gateway": _enum_value(_normalize_enum(GatewayMode, gateway))},
        )

    @property
    def accepted(self) -> bool:
        return self.status in {ExecutionStatus.SUBMITTED, ExecutionStatus.ACCEPTED, ExecutionStatus.FILLED}

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "operation_id": self.operation_id,
            "status": self.status.value,
            "reason": _enum_value(self.reason),
            "gateway_order_id": self.gateway_order_id,
            "capability": _enum_value(self.capability),
            "events": [event.to_dict() for event in self.events],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GatewayCapabilities:
    gateway: GatewayMode | str
    supported: set[GatewayCapability] = field(default_factory=set)
    native_protection: bool = False
    local_guardian: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "gateway", _normalize_enum(GatewayMode, self.gateway))
        object.__setattr__(self, "supported", {_normalize_enum(GatewayCapability, item) for item in self.supported})

    def supports(self, capability: GatewayCapability | str) -> bool:
        return _normalize_enum(GatewayCapability, capability) in self.supported


@dataclass(frozen=True)
class ReconcileRequest:
    gateway: GatewayMode | str
    staged_execution_mode: str
    symbol: str
    trade_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "gateway", _normalize_enum(GatewayMode, self.gateway))
        object.__setattr__(self, "symbol", _require_text(self.symbol, "symbol"))

    @property
    def idempotency_key(self) -> str:
        trade_key = self.trade_id or "all"
        return f"{self.gateway.value}:{self.staged_execution_mode}:{self.symbol}:{trade_key}"


@dataclass(frozen=True)
class ReconcileResult:
    request: ReconcileRequest
    positions: list[PositionView] = field(default_factory=list)
    orders: list[OrderView] = field(default_factory=list)
    protections: list[ProtectionOrderView] = field(default_factory=list)
    events: list[ExecutionEvent] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @property
    def has_gaps(self) -> bool:
        return bool(self.gaps)
