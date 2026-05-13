from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import Any

from trader.execution.gateways import BinanceLiveExecutionGateway
from trader.execution.models import (
    ExecutionEvent,
    ExecutionEventType,
    ExecutionReason,
    ExecutionSide,
    ExecutionStatus,
    GatewayMode,
    OrderIntent,
)
from trader.execution.order_semantics import OrderSemanticsError, select_order_semantics
from trader.execution.state import ExecutionStateRecord
from trader.live.dashboard import DashboardEvent
from trader.task.live_startup_self_check import task_requires_short_capability
from trader.utils.operate import OperateType

MANUAL_NOTIFY_MODE = "manual_notify"
AUTO_TRADE_MODE = "auto_trade"
AUTO_EXECUTION_EVENT_TYPE = "auto_execution_outcome"


class LiveExecutionMode(str, Enum):
    MANUAL_NOTIFY = MANUAL_NOTIFY_MODE
    SMALL_LIVE_AUTO = "small_live_auto"
    FULL_LIVE_AUTO = "full_live_auto"
    AUTO_TRADE = "auto_trade"


class LiveShortExecution(str, Enum):
    DISABLED = "disabled"
    MARGIN_CROSS = "margin_cross"

class MarginBorrowBlockPolicy(str, Enum):
    SKIP_SHORT_CONTINUE = "skip_short_continue"
    AUTO_REPAY_THEN_RETRY_ONCE = "auto_repay_then_retry_once"
    HARD_FAIL_STOP_TASK = "hard_fail_stop_task"


class AutoExecutionStatus(str, Enum):
    SUBMITTED = "submitted"
    SKIPPED = "skipped"
    FAILED = "failed"


REAL_AUTO_MODES = {LiveExecutionMode.SMALL_LIVE_AUTO.value, LiveExecutionMode.FULL_LIVE_AUTO.value, LiveExecutionMode.AUTO_TRADE.value}
STAGED_AUTO_MODES = set(REAL_AUTO_MODES)
SUPPORTED_LIVE_EXECUTION_MODES = {LiveExecutionMode.MANUAL_NOTIFY.value, *STAGED_AUTO_MODES}
SUPPORTED_SHORT_EXECUTION_MODES = {LiveShortExecution.DISABLED.value, LiveShortExecution.MARGIN_CROSS.value}
SUPPORTED_MARGIN_BORROW_BLOCK_POLICIES = {
    MarginBorrowBlockPolicy.SKIP_SHORT_CONTINUE.value,
    MarginBorrowBlockPolicy.AUTO_REPAY_THEN_RETRY_ONCE.value,
    MarginBorrowBlockPolicy.HARD_FAIL_STOP_TASK.value,
}


@dataclass
class AutoExecutionOutcome:
    task_id: int
    mode: str
    market: str
    operation_id: str
    operation_type: str
    signal_time: int
    signal_price: float
    requested_notional: float
    requested_quantity: float
    effective_notional: float
    effective_quantity: float
    status: AutoExecutionStatus | str
    reason: str | None = None
    exchange_order: Any = None
    execution_events: list[dict[str, Any]] = field(default_factory=list)
    execution_state_records: list[ExecutionStateRecord] = field(default_factory=list, repr=False)
    native_protection: bool = False
    local_guardian: bool = False

    def to_dict(self) -> dict[str, Any]:
        status = self.status.value if isinstance(self.status, Enum) else str(self.status)
        return {
            "task_id": self.task_id,
            "mode": self.mode,
            "market": self.market,
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "signal_time": self.signal_time,
            "signal_price": self.signal_price,
            "requested_notional": self.requested_notional,
            "requested_quantity": self.requested_quantity,
            "effective_notional": self.effective_notional,
            "effective_quantity": self.effective_quantity,
            "status": status,
            "reason": self.reason,
            "exchange_order": self.exchange_order,
            "execution_events": list(self.execution_events),
            "native_protection": self.native_protection,
            "local_guardian": self.local_guardian,
        }

    def with_native_protection(self, enabled: bool) -> "AutoExecutionOutcome":
        self.native_protection = bool(enabled)
        return self


def normalize_live_execution_mode(value: str | LiveExecutionMode | None) -> str:
    raw = value.value if isinstance(value, LiveExecutionMode) else value
    mode = str(raw or LiveExecutionMode.AUTO_TRADE.value).strip().lower()
    if mode in ("manual", "notify"):
        mode = LiveExecutionMode.MANUAL_NOTIFY.value
    if mode == "paper_auto":
        raise ValueError("paper_auto is no longer supported; use backtest mode for testing or manual_notify for no-order realtime operation")
    if mode not in SUPPORTED_LIVE_EXECUTION_MODES:
        raise ValueError(f"unsupported live_execution_mode: {raw}")
    return mode


def normalize_live_short_execution(value: str | LiveShortExecution | None) -> str:
    raw = value.value if isinstance(value, LiveShortExecution) else value
    mode = str(raw or LiveShortExecution.DISABLED.value).strip().lower()
    if mode not in SUPPORTED_SHORT_EXECUTION_MODES:
        raise ValueError(f"unsupported live_short_execution: {raw}")
    return mode


def normalize_margin_borrow_block_policy(value: str | MarginBorrowBlockPolicy | None) -> str:
    raw = value.value if isinstance(value, MarginBorrowBlockPolicy) else value
    mode = str(raw or MarginBorrowBlockPolicy.SKIP_SHORT_CONTINUE.value).strip().lower()
    if mode not in SUPPORTED_MARGIN_BORROW_BLOCK_POLICIES:
        raise ValueError(f"unsupported live_margin_borrow_block_policy: {raw}")
    return mode


def is_manual_notify_mode(value: str | None) -> bool:
    return normalize_live_execution_mode(value) == LiveExecutionMode.MANUAL_NOTIFY.value


def is_paper_auto_mode(value: str | None) -> bool:
    return False


def is_real_auto_mode(value: str | None) -> bool:
    return normalize_live_execution_mode(value) in REAL_AUTO_MODES


def operation_identity(op) -> str:
    signal_event_id = getattr(op, "signal_event_id", None)
    if signal_event_id:
        return f"signal_event_id:{signal_event_id}"
    side = op.otype.name if getattr(op, "otype", None) else "UNKNOWN"
    price = float(getattr(op, "price", 0.0) or 0.0)
    return f"operation:{side}:{int(getattr(op, 'dtime', 0) or 0)}:{price:.12g}"


def execution_outcome_event(strategy_id: int, outcome: AutoExecutionOutcome) -> DashboardEvent:
    return DashboardEvent(
        event_type=AUTO_EXECUTION_EVENT_TYPE,
        strategy_id=strategy_id,
        event_time=int(outcome.signal_time),
        payload=outcome.to_dict(),
    )


class AutoExecutionRouter:
    def __init__(self, tcfg, exchange=None, cfg=None, log=None):
        self.tcfg = tcfg
        self.exchange = exchange
        self.cfg = cfg
        self.log = log
        self.mode = normalize_live_execution_mode(getattr(tcfg, "live_execution_mode", None))
        self.short_execution = normalize_live_short_execution(getattr(tcfg, "live_short_execution", None))
        self.margin_borrow_block_policy = normalize_margin_borrow_block_policy(
            getattr(tcfg, "live_margin_borrow_block_policy", None)
        )
        self.requires_short_capability = task_requires_short_capability(tcfg)
        self.real_short_position = 0.0
        self.real_long_position = 0.0
        self._protection_order_ids_by_trade: dict[str, str] = {}
        self._seen_operation_ids: set[str] = set()
        self.outcomes: list[AutoExecutionOutcome] = []

    @property
    def market(self) -> str:
        return self.tcfg.symbol_interval.symbol()

    def route(self, op) -> AutoExecutionOutcome:
        op_id = operation_identity(op)
        if op_id in self._seen_operation_ids:
            return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="duplicate_operation"))
        self._seen_operation_ids.add(op_id)

        if self.mode == LiveExecutionMode.MANUAL_NOTIFY.value:
            return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="manual_notify_no_order"))
        return self._route_real(op)

    def _outcome(
        self,
        op,
        status: AutoExecutionStatus,
        *,
        reason: str | None = None,
        requested_notional: float = 0.0,
        requested_quantity: float = 0.0,
        effective_notional: float = 0.0,
        effective_quantity: float = 0.0,
        exchange_order=None,
        execution_events: list[dict[str, Any]] | None = None,
        execution_state_records: list[ExecutionStateRecord] | None = None,
    ) -> AutoExecutionOutcome:
        normalized_events = execution_events
        if normalized_events is None:
            normalized_events = self._normalized_execution_events(
                op,
                status=status,
                reason=reason,
                exchange_order=exchange_order,
                quantity=effective_quantity,
            )
        return AutoExecutionOutcome(
            task_id=int(self.tcfg.id),
            mode=self.mode,
            market=self.market,
            operation_id=operation_identity(op),
            operation_type=op.otype.name if getattr(op, "otype", None) else "UNKNOWN",
            signal_time=int(getattr(op, "dtime", 0) or 0),
            signal_price=float(getattr(op, "price", 0.0) or 0.0),
            requested_notional=float(requested_notional),
            requested_quantity=float(requested_quantity),
            effective_notional=float(effective_notional),
            effective_quantity=float(effective_quantity),
            status=status,
            reason=reason,
            exchange_order=exchange_order,
            execution_events=normalized_events,
            execution_state_records=list(execution_state_records or []),
            native_protection=False,
            local_guardian=False,
        )

    def _record(self, outcome: AutoExecutionOutcome) -> AutoExecutionOutcome:
        self.outcomes.append(outcome)
        self._audit_outcome(outcome)
        return outcome

    def _audit_outcome(self, outcome: AutoExecutionOutcome) -> None:
        logger = getattr(self, "log", None)
        if logger is None:
            return
        order_id = self._exchange_order_id(outcome.exchange_order)
        payload = {
            "task_id": outcome.task_id,
            "mode": outcome.mode,
            "market": outcome.market,
            "operation_id": outcome.operation_id,
            "operation_type": outcome.operation_type,
            "status": outcome.status.value if isinstance(outcome.status, Enum) else str(outcome.status),
            "reason": outcome.reason,
            "order_id": order_id,
            "effective_quantity": outcome.effective_quantity,
            "effective_notional": outcome.effective_notional,
        }
        if outcome.status == AutoExecutionStatus.SUBMITTED:
            if not order_id:
                logger.error(f"[auto_execution] submitted_without_order_id {payload}")
            else:
                logger.info(f"[auto_execution] submitted {payload}")
            return
        if outcome.status == AutoExecutionStatus.FAILED:
            logger.error(f"[auto_execution] failed {payload}")
            return
        if outcome.status == AutoExecutionStatus.SKIPPED and str(outcome.reason or "").startswith("margin_borrow_blocked_-3006"):
            logger.warning(f"[auto_execution] margin_borrow_blocked {payload}")

    def _gateway_mode(self) -> GatewayMode:
        if self.mode == LiveExecutionMode.MANUAL_NOTIFY.value:
            return GatewayMode.NOTIFICATION_ONLY
        return GatewayMode.BINANCE_LIVE

    def _normalized_execution_events(
        self,
        op,
        *,
        status: AutoExecutionStatus,
        reason: str | None,
        exchange_order: Any,
        quantity: float,
    ) -> list[dict[str, Any]]:
        if status == AutoExecutionStatus.SUBMITTED:
            statuses = [ExecutionStatus.SUBMITTED, ExecutionStatus.ACCEPTED]
        elif status == AutoExecutionStatus.FAILED:
            statuses = [ExecutionStatus.FAILED]
        else:
            statuses = [ExecutionStatus.SKIPPED]
        order_id = self._exchange_order_id(exchange_order)
        events = []
        for normalized_status in statuses:
            events.append(
                ExecutionEvent(
                    event_type=self._event_type_for_execution_status(normalized_status),
                    gateway=self._gateway_mode(),
                    staged_execution_mode=self.mode,
                    intent_id=operation_identity(op),
                    operation_id=operation_identity(op),
                    symbol=self.market,
                    order_id=order_id,
                    status=normalized_status,
                    reason=ExecutionReason.GATEWAY_REJECTED if normalized_status in (ExecutionStatus.FAILED, ExecutionStatus.SKIPPED) else None,
                    quantity=float(quantity or 0.0),
                    price=float(getattr(op, "price", 0.0) or 0.0),
                    metadata={
                        "legacy_status": status.value if isinstance(status, Enum) else str(status),
                        "legacy_reason": reason,
                        "operation_type": getattr(getattr(op, "otype", None), "name", "UNKNOWN"),
                    },
                ).to_dict()
            )
        return events

    def _event_type_for_execution_status(self, status: ExecutionStatus) -> ExecutionEventType:
        if status == ExecutionStatus.SUBMITTED:
            return ExecutionEventType.ORDER_SUBMITTED
        if status == ExecutionStatus.ACCEPTED:
            return ExecutionEventType.ORDER_ACCEPTED
        if status == ExecutionStatus.FILLED:
            return ExecutionEventType.ORDER_FILLED
        if status == ExecutionStatus.CANCELED:
            return ExecutionEventType.ORDER_CANCELED
        return ExecutionEventType.ORDER_REJECTED

    def _exchange_order_id(self, exchange_order) -> str | None:
        if isinstance(exchange_order, dict):
            value = exchange_order.get("orderId") or exchange_order.get("order_id") or exchange_order.get("clientOrderId")
            return str(value) if value is not None else None
        value = getattr(exchange_order, "order_id", None) or getattr(exchange_order, "orderId", None)
        return str(value) if value is not None else None

    def _valid_price(self, op) -> float | None:
        price = float(getattr(op, "price", 0.0) or 0.0)
        if price <= 0 or not isfinite(price):
            return None
        return price

    def _route_real(self, op) -> AutoExecutionOutcome:
        price = self._valid_price(op)
        if price is None:
            return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="invalid_price"))

        otype = getattr(op, "otype", None)
        if otype == OperateType.RISK_UPDATE:
            return self._route_real_risk_update(op, price)
        if otype == OperateType.SHORT:
            return self._route_real_short(op, price)
        if otype in (OperateType.BUY, OperateType.LONG):
            return self._route_real_long(op, price)
        if otype == OperateType.CLOSE and self.requires_short_capability:
            return self._route_real_short_close(op, price)
        if otype == OperateType.SELL:
            return self._route_real_exit(op, price)
        return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="unsupported_operation"))

    def _requested_notional(self) -> float:
        if self.mode == LiveExecutionMode.SMALL_LIVE_AUTO.value:
            return float(getattr(self.tcfg, "live_trade_max_notional", 0.0) or 0.0)
        if getattr(self.tcfg, "free", -1) >= 0:
            return float(self.tcfg.free)
        return float(getattr(self.cfg, "cash", 0.0) or 0.0)

    def _route_real_long(self, op, price: float) -> AutoExecutionOutcome:
        notional = self._requested_notional()
        if self.mode == LiveExecutionMode.SMALL_LIVE_AUTO.value and notional <= 0:
            return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="invalid_live_trade_max_notional"))
        if notional <= 0 or not isfinite(notional):
            return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="invalid_notional"))
        quantity = notional / price
        if quantity <= 0 or not isfinite(quantity):
            return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="invalid_quantity"))
        constraint_reason = self._exchange_constraint_reason(op, quantity, notional)
        if constraint_reason:
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.SKIPPED,
                    reason=constraint_reason,
                    requested_notional=notional,
                    requested_quantity=quantity,
                    effective_notional=notional,
                    effective_quantity=quantity,
                )
            )
        if self.requires_short_capability and self._margin_ready():
            outcome = self._submit_margin(op, notional, quantity, OperateType.BUY)
            return outcome
        cash = self._balance(self.tcfg.symbol_interval.sy.quote)
        if cash < notional:
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.SKIPPED,
                    reason="insufficient_quote_balance",
                    requested_notional=notional,
                    requested_quantity=quantity,
                    effective_notional=notional,
                    effective_quantity=quantity,
                )
            )
        outcome = self._submit_spot(op, notional, quantity, op.otype)
        if outcome.status == AutoExecutionStatus.SUBMITTED and op.otype in (OperateType.BUY, OperateType.LONG):
            self.real_long_position += quantity
        return outcome

    def _route_real_exit(self, op, price: float) -> AutoExecutionOutcome:
        base_balance = self.real_long_position if self.real_long_position > 0 else self._balance(self.tcfg.symbol_interval.sy.base)
        if base_balance <= 0:
            return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="empty_or_unknown_position"))
        notional = base_balance * price
        constraint_reason = self._exchange_constraint_reason(op, base_balance, notional)
        if constraint_reason:
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.SKIPPED,
                    reason=constraint_reason,
                    requested_notional=notional,
                    requested_quantity=base_balance,
                    effective_notional=notional,
                    effective_quantity=base_balance,
                )
            )
        if self.requires_short_capability and self._margin_ready():
            return self._submit_margin(op, notional, base_balance, OperateType.SELL)
        outcome = self._submit_spot(op, notional, base_balance, OperateType.SELL)
        if outcome.status == AutoExecutionStatus.SUBMITTED and self.real_long_position > 0:
            self.real_long_position = 0.0
        return outcome

    def _route_real_short(self, op, price: float) -> AutoExecutionOutcome:
        notional = self._requested_notional()
        if not self.requires_short_capability:
            quantity = notional / price if price > 0 and notional > 0 else 0.0
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.SKIPPED,
                    reason="real_short_execution_disabled",
                    requested_notional=notional,
                    requested_quantity=quantity,
                    effective_notional=notional if notional > 0 else 0.0,
                    effective_quantity=quantity,
                )
            )
        if self.mode == LiveExecutionMode.SMALL_LIVE_AUTO.value and notional <= 0:
            return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="invalid_live_trade_max_notional"))
        if not self._margin_ready():
            return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="margin_not_ready"))
        quantity = notional / price
        if quantity <= 0 or not isfinite(quantity):
            return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="invalid_quantity"))
        constraint_reason = self._exchange_constraint_reason(op, quantity, notional)
        if constraint_reason:
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.SKIPPED,
                    reason=constraint_reason,
                    requested_notional=notional,
                    requested_quantity=quantity,
                    effective_notional=notional,
                    effective_quantity=quantity,
                )
            )
        outcome = self._submit_margin(op, notional, quantity, OperateType.SHORT)
        if outcome.status == AutoExecutionStatus.SUBMITTED:
            self.real_short_position += quantity
        return outcome

    def _route_real_short_close(self, op, price: float) -> AutoExecutionOutcome:
        if self.real_short_position <= 0:
            return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="unknown_short_exposure"))
        quantity = self.real_short_position
        notional = quantity * price
        if not self._margin_ready():
            return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="margin_not_ready"))
        constraint_reason = self._exchange_constraint_reason(op, quantity, notional)
        if constraint_reason:
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.SKIPPED,
                    reason=constraint_reason,
                    requested_notional=notional,
                    requested_quantity=quantity,
                    effective_notional=notional,
                    effective_quantity=quantity,
                )
            )
        outcome = self._submit_margin(op, notional, quantity, OperateType.CLOSE)
        if outcome.status == AutoExecutionStatus.SUBMITTED:
            self.real_short_position = 0.0
        return outcome

    def _balance(self, asset: str) -> float:
        if self.exchange is None or not hasattr(self.exchange, "get_account_balance"):
            return 0.0
        return float(self.exchange.get_account_balance(asset) or 0.0)

    def _margin_ready(self) -> bool:
        if self.exchange is None:
            return False
        checker = getattr(self.exchange, "is_cross_margin_ready", None)
        if checker is None:
            return hasattr(self.exchange, "new_margin_order")
        return bool(checker())

    def _exchange_constraint_reason(self, op, quantity: float, notional: float) -> str | None:
        validator = getattr(self.exchange, "validate_order_size", None) if self.exchange is not None else None
        if validator is None:
            return None
        result = validator(self.tcfg.symbol_interval.sy, getattr(op, "otype", None), quantity, notional)
        if result is True or result is None:
            return None
        if result is False:
            return "exchange_order_size_rejected"
        return str(result)

    def _submit_spot(self, op, notional: float, quantity: float, order_type: OperateType) -> AutoExecutionOutcome:
        side = ExecutionSide.LONG
        try:
            selection = select_order_semantics(
                op,
                symbol=self.market,
                side=side,
                quantity=quantity,
                notional=notional,
                allow_native_protection=True,
            )
        except OrderSemanticsError as exc:
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.SKIPPED,
                    reason=str(exc),
                    requested_notional=notional,
                    requested_quantity=quantity,
                    effective_notional=notional,
                    effective_quantity=quantity,
                )
            )
        if selection.order is None:
            return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="unsupported_operation"))

        try:
            gateway = BinanceLiveExecutionGateway(self.exchange, staged_execution_mode=self.mode)
            if order_type in (OperateType.BUY, OperateType.LONG):
                result = gateway.open_position(selection.order)
            else:
                result = gateway.close_position(selection.order)
            protection_result = gateway.place_protection(selection.risk) if result.accepted and selection.risk is not None else None
            fail_safe_result = self._fail_safe_close(gateway, selection.order, protection_result)
        except Exception as exc:
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.FAILED,
                    reason=str(exc),
                    requested_notional=notional,
                    requested_quantity=quantity,
                    effective_notional=notional,
                    effective_quantity=quantity,
                )
            )
        status = AutoExecutionStatus.SUBMITTED if result.accepted else AutoExecutionStatus.FAILED
        reason = None if result.accepted else str(result.reason or "exchange_order_failed")
        events = [event.to_dict() for event in result.events]
        records = [self._state_record_for_order(selection.order, result, op)]
        native_protection = False
        exchange_order = {"orderId": result.gateway_order_id} if result.gateway_order_id is not None else None
        if protection_result is not None:
            events.extend(event.to_dict() for event in protection_result.events)
            records.append(self._state_record_for_risk(selection.risk, protection_result, op))
            if protection_result.accepted:
                native_protection = True
                self._remember_protection_order(selection.risk, protection_result)
            else:
                status = AutoExecutionStatus.FAILED
                reason = str(protection_result.reason or "protection_failed")
                if fail_safe_result is not None:
                    events.extend(event.to_dict() for event in fail_safe_result.events)
                    records.append(self._state_record_for_order(self._close_intent_for_fail_safe(selection.order), fail_safe_result, op))
                    reason = f"{reason}; fail_safe_close_submitted"
        return self._record(
            self._outcome(
                op,
                status,
                reason=reason,
                requested_notional=notional,
                requested_quantity=quantity,
                effective_notional=notional,
                effective_quantity=quantity,
                exchange_order=exchange_order,
                execution_events=events,
                execution_state_records=records,
            )
            .with_native_protection(native_protection)
        )

    def _route_real_risk_update(self, op, price: float) -> AutoExecutionOutcome:
        side = self._risk_update_side(op)
        if side == ExecutionSide.SHORT:
            if not self.requires_short_capability or not self._margin_ready():
                return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="margin_not_ready"))
            quantity = self.real_short_position
            empty_reason = "unknown_short_exposure"
        else:
            quantity = self.real_long_position if self.real_long_position > 0 else self._balance(self.tcfg.symbol_interval.sy.base)
            empty_reason = "empty_or_unknown_position"
        if quantity <= 0:
            return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason=empty_reason))
        notional = quantity * price
        try:
            self._attach_known_protection_order_id(op)
            selection = select_order_semantics(op, symbol=self.market, side=side, quantity=quantity, notional=notional)
            if selection.risk is None:
                return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="missing_protection_intent"))
            result = BinanceLiveExecutionGateway(self.exchange, staged_execution_mode=self.mode).replace_protection(selection.risk)
        except OrderSemanticsError as exc:
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.SKIPPED,
                    reason=str(exc),
                    requested_notional=notional,
                    requested_quantity=quantity,
                    effective_notional=notional,
                    effective_quantity=quantity,
                )
            )
        except Exception as exc:
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.FAILED,
                    reason=str(exc),
                    requested_notional=notional,
                    requested_quantity=quantity,
                    effective_notional=notional,
                    effective_quantity=quantity,
                )
            )
        return self._record(
            self._outcome(
                op,
                AutoExecutionStatus.SUBMITTED if result.accepted else AutoExecutionStatus.FAILED,
                reason=None if result.accepted else str(result.reason or "protection_failed"),
                requested_notional=notional,
                requested_quantity=quantity,
                effective_notional=notional,
                effective_quantity=quantity,
                exchange_order={"orderId": result.gateway_order_id} if result.gateway_order_id is not None else None,
                execution_events=[event.to_dict() for event in result.events],
                execution_state_records=[self._state_record_for_risk(selection.risk, result, op)],
            ).with_native_protection(result.accepted)
        )

    def _submit_margin(self, op, notional: float, quantity: float, order_type: OperateType) -> AutoExecutionOutcome:
        try:
            execution_side = ExecutionSide.LONG if order_type in (OperateType.BUY, OperateType.SELL) else ExecutionSide.SHORT
            selection = select_order_semantics(
                op,
                symbol=self.market,
                side=execution_side,
                quantity=quantity,
                notional=notional,
                allow_native_protection=True,
            )
            if selection.order is None:
                return self._record(self._outcome(op, AutoExecutionStatus.SKIPPED, reason="unsupported_operation"))
            gateway = BinanceLiveExecutionGateway(self.exchange, staged_execution_mode=self.mode)
            result = gateway.open_position(selection.order) if order_type in (OperateType.BUY, OperateType.SHORT) else gateway.close_position(selection.order)
            if order_type == OperateType.SHORT and self._is_margin_borrow_block_result(result):
                return self._handle_margin_borrow_block(
                    op=op,
                    notional=notional,
                    quantity=quantity,
                    gateway=gateway,
                    selection=selection,
                    initial_result=result,
                )
            protection_result = gateway.place_protection(selection.risk) if result.accepted and selection.risk is not None else None
            fail_safe_result = self._fail_safe_close(gateway, selection.order, protection_result)
        except OrderSemanticsError as exc:
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.SKIPPED,
                    reason=str(exc),
                    requested_notional=notional,
                    requested_quantity=quantity,
                    effective_notional=notional,
                    effective_quantity=quantity,
                )
            )
        except Exception as exc:
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.FAILED,
                    reason=str(exc),
                    requested_notional=notional,
                    requested_quantity=quantity,
                    effective_notional=notional,
                    effective_quantity=quantity,
                )
            )
        status = AutoExecutionStatus.SUBMITTED if result.accepted else AutoExecutionStatus.FAILED
        reason = None if result.accepted else str(result.reason or "exchange_order_failed")
        events = [event.to_dict() for event in result.events]
        records = [self._state_record_for_order(selection.order, result, op)]
        native_protection = False
        if protection_result is not None:
            events.extend(event.to_dict() for event in protection_result.events)
            records.append(self._state_record_for_risk(selection.risk, protection_result, op))
            if protection_result.accepted:
                native_protection = True
                self._remember_protection_order(selection.risk, protection_result)
            else:
                status = AutoExecutionStatus.FAILED
                reason = str(protection_result.reason or "protection_failed")
                if fail_safe_result is not None:
                    events.extend(event.to_dict() for event in fail_safe_result.events)
                    records.append(self._state_record_for_order(self._close_intent_for_fail_safe(selection.order), fail_safe_result, op))
                    reason = f"{reason}; fail_safe_close_submitted"
        return self._record(
            self._outcome(
                op,
                status,
                reason=reason,
                requested_notional=notional,
                requested_quantity=quantity,
                effective_notional=notional,
                effective_quantity=quantity,
                exchange_order={"orderId": result.gateway_order_id} if result.gateway_order_id is not None else None,
                execution_events=events,
                execution_state_records=records,
            ).with_native_protection(native_protection)
        )

    def _handle_margin_borrow_block(self, *, op, notional: float, quantity: float, gateway: BinanceLiveExecutionGateway, selection, initial_result) -> AutoExecutionOutcome:
        policy = self.margin_borrow_block_policy
        base_reason = f"margin_borrow_blocked_-3006 policy={policy}"
        initial_events = [event.to_dict() for event in initial_result.events]
        initial_records = [self._state_record_for_order(selection.order, initial_result, op)]
        if policy == MarginBorrowBlockPolicy.HARD_FAIL_STOP_TASK.value:
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.FAILED,
                    reason=base_reason,
                    requested_notional=notional,
                    requested_quantity=quantity,
                    effective_notional=notional,
                    effective_quantity=quantity,
                    exchange_order={"orderId": initial_result.gateway_order_id} if initial_result.gateway_order_id is not None else None,
                    execution_events=initial_events,
                    execution_state_records=initial_records,
                )
            )
        if policy == MarginBorrowBlockPolicy.SKIP_SHORT_CONTINUE.value:
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.SKIPPED,
                    reason=base_reason,
                    requested_notional=notional,
                    requested_quantity=quantity,
                    effective_notional=notional,
                    effective_quantity=quantity,
                    execution_events=initial_events,
                    execution_state_records=initial_records,
                )
            )
        repay = self._attempt_margin_auto_repay_for_block(selection.order.symbol)
        if not repay.get("ok"):
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.SKIPPED,
                    reason=f"{base_reason} auto_repay_unavailable",
                    requested_notional=notional,
                    requested_quantity=quantity,
                    effective_notional=notional,
                    effective_quantity=quantity,
                    execution_events=initial_events,
                    execution_state_records=initial_records,
                )
            )
        retry_result = gateway.open_position(selection.order)
        retry_events = [event.to_dict() for event in retry_result.events]
        retry_records = [self._state_record_for_order(selection.order, retry_result, op)]
        if self._is_margin_borrow_block_result(retry_result):
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.SKIPPED,
                    reason=f"{base_reason} auto_repay_retry_failed",
                    requested_notional=notional,
                    requested_quantity=quantity,
                    effective_notional=notional,
                    effective_quantity=quantity,
                    execution_events=initial_events + retry_events,
                    execution_state_records=initial_records + retry_records,
                )
            )
        if not retry_result.accepted:
            return self._record(
                self._outcome(
                    op,
                    AutoExecutionStatus.FAILED,
                    reason=f"{base_reason} retry_non_borrow_failure",
                    requested_notional=notional,
                    requested_quantity=quantity,
                    effective_notional=notional,
                    effective_quantity=quantity,
                    execution_events=initial_events + retry_events,
                    execution_state_records=initial_records + retry_records,
                )
            )
        protection_result = gateway.place_protection(selection.risk) if selection.risk is not None else None
        events = initial_events + retry_events
        records = initial_records + retry_records
        native_protection = False
        status = AutoExecutionStatus.SUBMITTED
        reason = f"{base_reason} auto_repay_retry_passed"
        if protection_result is not None:
            events.extend(event.to_dict() for event in protection_result.events)
            records.append(self._state_record_for_risk(selection.risk, protection_result, op))
            if protection_result.accepted:
                native_protection = True
                self._remember_protection_order(selection.risk, protection_result)
            else:
                status = AutoExecutionStatus.FAILED
                reason = f"{base_reason} protection_failed_after_retry"
        return self._record(
            self._outcome(
                op,
                status,
                reason=reason,
                requested_notional=notional,
                requested_quantity=quantity,
                effective_notional=notional,
                effective_quantity=quantity,
                exchange_order={"orderId": retry_result.gateway_order_id} if retry_result.gateway_order_id is not None else None,
                execution_events=events,
                execution_state_records=records,
            ).with_native_protection(native_protection)
        )

    def _attempt_margin_auto_repay_for_block(self, symbol: str) -> dict[str, Any]:
        if self.exchange is None:
            return {"ok": False, "reason": "exchange_missing"}
        helper = getattr(self.exchange, "auto_repay_for_borrow_block", None)
        if callable(helper):
            try:
                return dict(helper(symbol))
            except Exception as exc:
                return {"ok": False, "reason": str(exc)}
        return {"ok": False, "reason": "auto_repay_not_supported"}

    def _is_margin_borrow_block_result(self, result) -> bool:
        if getattr(result, "accepted", False):
            return False
        candidates: list[str] = []
        for event in getattr(result, "events", []) or []:
            metadata = getattr(event, "metadata", None)
            if isinstance(metadata, dict):
                candidates.append(str(metadata.get("raw_payload", "")))
        candidates.append(str(getattr(result, "metadata", "")))
        candidates.append(str(getattr(result, "reason", "")))
        text = " ".join(candidates).lower()
        return "-3006" in text or "borrow amount has exceed maximum borrow amount" in text

    def _risk_update_side(self, op) -> ExecutionSide:
        framework_trade = getattr(op, "framework_trade", None)
        direction = framework_trade.get("direction") if isinstance(framework_trade, dict) else None
        if str(direction or "").upper() == "SHORT":
            return ExecutionSide.SHORT
        return ExecutionSide.LONG

    def _attach_known_protection_order_id(self, op) -> None:
        if str(getattr(op, "protection_order_id", "") or "").strip():
            return
        framework_trade = getattr(op, "framework_trade", None)
        trade_id = framework_trade.get("trade_id") if isinstance(framework_trade, dict) else None
        if trade_id is None:
            return
        order_id = self._protection_order_ids_by_trade.get(str(trade_id))
        if order_id:
            setattr(op, "protection_order_id", order_id)

    def _remember_protection_order(self, intent, result) -> None:
        trade_id = str(getattr(intent, "trade_id", "") or "").strip()
        order_id = self._first_gateway_order_id(getattr(result, "gateway_order_id", None))
        if trade_id and order_id:
            self._protection_order_ids_by_trade[trade_id] = order_id

    def _first_gateway_order_id(self, value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        return text.split(",", 1)[0].strip() or None

    def _close_intent_for_fail_safe(self, entry_intent: OrderIntent) -> OrderIntent:
        return OrderIntent.close(
            intent_id=f"{entry_intent.intent_id}:fail_safe_close",
            operation_id=entry_intent.operation_id,
            symbol=entry_intent.symbol,
            side=entry_intent.side,
            quantity=entry_intent.quantity,
            notional=entry_intent.notional,
            price=entry_intent.price,
            trade_id=entry_intent.trade_id,
            signal_event_id=entry_intent.signal_event_id,
            metadata={**dict(entry_intent.metadata), "fail_safe": "native_protection_unverified"},
        )

    def _fail_safe_close(self, gateway: BinanceLiveExecutionGateway, entry_intent: OrderIntent, protection_result) -> Any:
        if protection_result is None or protection_result.accepted:
            return None
        return gateway.close_position(self._close_intent_for_fail_safe(entry_intent))

    def _state_record_for_order(self, intent: OrderIntent, result, op) -> ExecutionStateRecord:
        return ExecutionStateRecord.from_order_intent(
            intent,
            gateway=GatewayMode.BINANCE_LIVE,
            staged_execution_mode=self.mode,
            status=result.status,
            exchange_order_id=result.gateway_order_id,
            timestamp=int(getattr(op, "dtime", 0) or 0),
        )

    def _state_record_for_risk(self, intent, result, op) -> ExecutionStateRecord:
        return ExecutionStateRecord.from_risk_intent(
            intent,
            gateway=GatewayMode.BINANCE_LIVE,
            staged_execution_mode=self.mode,
            status=result.status,
            exchange_order_id=result.gateway_order_id,
            protection_id=result.gateway_order_id,
            timestamp=int(getattr(op, "dtime", 0) or 0),
        )
