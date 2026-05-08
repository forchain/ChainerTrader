from __future__ import annotations

import time
from enum import Enum
from typing import Callable

from trader.execution import (
    ExecutionGateway,
    ExecutionReason,
    ExecutionResult,
    ExecutionSide,
    ExecutionStateStore,
    ExecutionStatus,
    GatewayMode,
    OrderIntent,
    OrderIntentType,
    RiskIntent,
)
from trader.execution.state import ExecutionStateRecord
from trader.utils.operate import OperateType


class TradeLifecycleStatus(str, Enum):
    PENDING_ENTRY_CONFIRM = "pending_entry_confirm"
    OPENING = "opening"
    ACTIVE = "active"
    PENDING_EXIT_CONFIRM = "pending_exit_confirm"
    CLOSING = "closing"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class TradeLifecycleEngine:
    def apply_execution_result(
        self,
        current_status: TradeLifecycleStatus | str,
        intent: OrderIntent,
        result: ExecutionResult,
    ) -> TradeLifecycleStatus:
        current = current_status if isinstance(current_status, TradeLifecycleStatus) else TradeLifecycleStatus(str(current_status))
        if result.status in {ExecutionStatus.REJECTED, ExecutionStatus.FAILED, ExecutionStatus.SKIPPED}:
            return current
        if intent.intent_type == OrderIntentType.ENTRY:
            if result.status == ExecutionStatus.FILLED:
                return TradeLifecycleStatus.ACTIVE
            return TradeLifecycleStatus.OPENING
        if intent.intent_type == OrderIntentType.CLOSE:
            if result.status == ExecutionStatus.FILLED:
                return TradeLifecycleStatus.CLOSED
            return TradeLifecycleStatus.CLOSING
        if intent.intent_type == OrderIntentType.CANCEL:
            return TradeLifecycleStatus.CANCELLED
        return current


class RiskEngine:
    def protection_for_entry(
        self,
        entry_intent: OrderIntent,
        *,
        stop_price: float | None = None,
        take_profit_price: float | None = None,
        metadata: dict | None = None,
    ) -> RiskIntent:
        return RiskIntent.place_protection(
            intent_id=f"risk:{entry_intent.intent_id}",
            operation_id=entry_intent.operation_id,
            symbol=entry_intent.symbol,
            side=entry_intent.side,
            trade_id=str(entry_intent.trade_id or entry_intent.intent_id),
            quantity=float(entry_intent.quantity or 0.0),
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            signal_event_id=entry_intent.signal_event_id,
            metadata={**dict(entry_intent.metadata), **dict(metadata or {})},
        )

    def breakeven_replacement(
        self,
        entry_intent: OrderIntent,
        *,
        stop_price: float,
        replacement_of_order_id: str | None = None,
        metadata: dict | None = None,
    ) -> RiskIntent:
        return RiskIntent.replace_stop(
            intent_id=f"risk:{entry_intent.intent_id}:breakeven",
            operation_id=entry_intent.operation_id,
            symbol=entry_intent.symbol,
            side=entry_intent.side,
            trade_id=str(entry_intent.trade_id or entry_intent.intent_id),
            quantity=float(entry_intent.quantity or 0.0),
            stop_price=stop_price,
            replacement_of_order_id=replacement_of_order_id,
            signal_event_id=entry_intent.signal_event_id,
            metadata={**dict(entry_intent.metadata), **dict(metadata or {})},
        )


class LegacyStrategyExecutionAdapter:
    def __init__(self, *, symbol: str, default_quantity: float = 0.0, default_notional: float | None = None):
        self.symbol = symbol
        self.default_quantity = float(default_quantity or 0.0)
        self.default_notional = default_notional

    def order_intent_from_operation(self, op, *, trade_id: str | int | None = None) -> OrderIntent:
        side = self._side_for_operation(op)
        intent_id = self._intent_id(op)
        operation_id = self._operation_id(op)
        metadata = self._metadata_from_operation(op)
        signal_event_id = getattr(op, "signal_event_id", None)
        if getattr(op, "otype", None) in (OperateType.BUY, OperateType.LONG, OperateType.SHORT):
            return OrderIntent.entry(
                intent_id=intent_id,
                operation_id=operation_id,
                symbol=self.symbol,
                side=side,
                quantity=self.default_quantity,
                notional=self.default_notional,
                price=float(getattr(op, "price", 0.0) or 0.0) or None,
                trade_id=str(trade_id) if trade_id is not None else self._trade_id_from_operation(op),
                signal_event_id=signal_event_id,
                metadata=metadata,
            )
        return OrderIntent.close(
            intent_id=intent_id,
            operation_id=operation_id,
            symbol=self.symbol,
            side=side,
            quantity=self.default_quantity,
            notional=self.default_notional,
            price=float(getattr(op, "price", 0.0) or 0.0) or None,
            trade_id=str(trade_id) if trade_id is not None else self._trade_id_from_operation(op),
            signal_event_id=signal_event_id,
            metadata=metadata,
        )

    def risk_intent_from_operation(self, op, *, trade_id: str | int | None = None, side: ExecutionSide | str | None = None) -> RiskIntent | None:
        metadata = self._metadata_from_operation(op)
        framework_trade = metadata.get("framework_trade") if isinstance(metadata.get("framework_trade"), dict) else {}
        signal_metadata = metadata.get("signal_metadata") if isinstance(metadata.get("signal_metadata"), dict) else {}
        signal_event_id = getattr(op, "signal_event_id", None)
        resolved_side = side or self._side_from_direction(framework_trade.get("direction")) or self._side_for_operation(op)
        resolved_trade_id = str(trade_id) if trade_id is not None else self._trade_id_from_operation(op) or str(self._intent_id(op))
        stop_price = getattr(op, "stop_loss", None)
        if stop_price is None:
            stop_price = framework_trade.get("stop_price") or framework_trade.get("initial_stop_price") or signal_metadata.get("suggested_stop_price")
        take_profit_price = getattr(op, "take_profit", None)
        if take_profit_price is None:
            take_profit_price = framework_trade.get("take_profit")
        if getattr(op, "otype", None) == OperateType.RISK_UPDATE or getattr(op, "breakeven_new_stop", None) is not None:
            if stop_price is None:
                stop_price = getattr(op, "breakeven_new_stop", None) or getattr(op, "price", None)
            return RiskIntent.replace_stop(
                intent_id=f"risk:{self._intent_id(op)}",
                operation_id=self._operation_id(op),
                symbol=self.symbol,
                side=resolved_side,
                trade_id=resolved_trade_id,
                quantity=self.default_quantity,
                stop_price=float(stop_price),
                replacement_of_order_id=getattr(op, "protection_order_id", None),
                signal_event_id=signal_event_id,
                metadata=metadata,
            )
        if stop_price is None and take_profit_price is None:
            return None
        return RiskIntent.place_protection(
            intent_id=f"risk:{self._intent_id(op)}",
            operation_id=self._operation_id(op),
            symbol=self.symbol,
            side=resolved_side,
            trade_id=resolved_trade_id,
            quantity=self.default_quantity,
            stop_price=float(stop_price) if stop_price is not None else None,
            take_profit_price=float(take_profit_price) if take_profit_price is not None else None,
            signal_event_id=signal_event_id,
            metadata=metadata,
        )

    def _intent_id(self, op) -> str:
        signal_event_id = getattr(op, "signal_event_id", None)
        if signal_event_id:
            return f"intent:{signal_event_id}"
        return f"intent:{getattr(getattr(op, 'otype', None), 'name', 'UNKNOWN')}:{int(getattr(op, 'dtime', 0) or 0)}"

    def _operation_id(self, op) -> str:
        signal_event_id = getattr(op, "signal_event_id", None)
        if signal_event_id:
            return str(signal_event_id)
        side = getattr(getattr(op, "otype", None), "name", "UNKNOWN")
        dtime = int(getattr(op, "dtime", 0) or 0)
        price = float(getattr(op, "price", 0.0) or 0.0)
        return f"{side}:{dtime}:{price:.12g}"

    def _metadata_from_operation(self, op) -> dict:
        if hasattr(op, "to_dict"):
            payload = dict(op.to_dict())
        else:
            payload = {}
        for name in ("signal_metadata", "divergence_metadata", "framework_trade"):
            if hasattr(op, name):
                payload[name] = getattr(op, name)
        return payload

    def _trade_id_from_operation(self, op) -> str | None:
        framework_trade = getattr(op, "framework_trade", None)
        if isinstance(framework_trade, dict) and framework_trade.get("trade_id") is not None:
            return str(framework_trade["trade_id"])
        return None

    def _side_for_operation(self, op) -> ExecutionSide:
        otype = getattr(op, "otype", None)
        if otype in (OperateType.SHORT, OperateType.CLOSE):
            return ExecutionSide.SHORT
        direction = None
        framework_trade = getattr(op, "framework_trade", None)
        if isinstance(framework_trade, dict):
            direction = framework_trade.get("direction")
        return self._side_from_direction(direction) or ExecutionSide.LONG

    def _side_from_direction(self, direction) -> ExecutionSide | None:
        if str(direction or "").upper() == "SHORT":
            return ExecutionSide.SHORT
        if str(direction or "").upper() == "LONG":
            return ExecutionSide.LONG
        return None


class ExecutionOrchestrator:
    def __init__(
        self,
        gateway: ExecutionGateway,
        *,
        gateway_mode: GatewayMode | str,
        staged_execution_mode: str,
        state_store: ExecutionStateStore | None = None,
        clock: Callable[[], int] | None = None,
    ):
        self.gateway = gateway
        self.gateway_mode = gateway_mode if isinstance(gateway_mode, GatewayMode) else GatewayMode(str(gateway_mode))
        self.staged_execution_mode = staged_execution_mode
        self.state_store = state_store
        self.clock = clock or (lambda: int(time.time()))

    async def execute_order(self, intent: OrderIntent) -> ExecutionResult:
        reservation = await self._reserve_order(intent)
        if reservation is False:
            return self._duplicate_result(intent.intent_id, intent.operation_id, intent.idempotency_key)
        if intent.intent_type == OrderIntentType.ENTRY:
            result = self.gateway.open_position(intent)
        elif intent.intent_type == OrderIntentType.CLOSE:
            result = self.gateway.close_position(intent)
        else:
            result = self.gateway.cancel_order(intent)
        await self._save_order_result(intent, result)
        return result

    async def execute_risk(self, intent: RiskIntent) -> ExecutionResult:
        reservation = await self._reserve_risk(intent)
        if reservation is False:
            return self._duplicate_result(intent.intent_id, intent.operation_id, intent.idempotency_key)
        if intent.action.value == "replace_protection":
            result = self.gateway.replace_protection(intent)
        elif intent.action.value == "cancel_protection":
            result = self.gateway.cancel_order(
                OrderIntent.close(
                    intent_id=intent.intent_id,
                    operation_id=intent.operation_id,
                    symbol=intent.symbol,
                    side=intent.side,
                    quantity=intent.quantity,
                    trade_id=intent.trade_id,
                    signal_event_id=intent.signal_event_id,
                    metadata=dict(intent.metadata),
                )
            )
        else:
            result = self.gateway.place_protection(intent)
        await self._save_risk_result(intent, result)
        return result

    async def _reserve_order(self, intent: OrderIntent) -> bool:
        if self.state_store is None:
            return True
        record = ExecutionStateRecord.from_order_intent(
            intent,
            gateway=self.gateway_mode,
            staged_execution_mode=self.staged_execution_mode,
            status=ExecutionStatus.SUBMITTED,
            timestamp=self.clock(),
        )
        reservation = await self.state_store.reserve(record)
        return bool(reservation.created)

    async def _reserve_risk(self, intent: RiskIntent) -> bool:
        if self.state_store is None:
            return True
        record = ExecutionStateRecord.from_risk_intent(
            intent,
            gateway=self.gateway_mode,
            staged_execution_mode=self.staged_execution_mode,
            status=ExecutionStatus.SUBMITTED,
            timestamp=self.clock(),
        )
        reservation = await self.state_store.reserve(record)
        return bool(reservation.created)

    async def _save_order_result(self, intent: OrderIntent, result: ExecutionResult) -> None:
        if self.state_store is None:
            return
        record = ExecutionStateRecord.from_order_intent(
            intent,
            gateway=self.gateway_mode,
            staged_execution_mode=self.staged_execution_mode,
            status=result.status,
            exchange_order_id=result.gateway_order_id,
            timestamp=self.clock(),
        )
        await self.state_store.save(record)

    async def _save_risk_result(self, intent: RiskIntent, result: ExecutionResult) -> None:
        if self.state_store is None:
            return
        record = ExecutionStateRecord.from_risk_intent(
            intent,
            gateway=self.gateway_mode,
            staged_execution_mode=self.staged_execution_mode,
            status=result.status,
            exchange_order_id=result.gateway_order_id,
            protection_id=result.gateway_order_id,
            timestamp=self.clock(),
        )
        await self.state_store.save(record)

    def _duplicate_result(self, intent_id: str, operation_id: str, idempotency_key: str) -> ExecutionResult:
        return ExecutionResult(
            intent_id=intent_id,
            operation_id=operation_id,
            status=ExecutionStatus.SKIPPED,
            reason=ExecutionReason.DUPLICATE_INTENT,
            metadata={"idempotency_key": idempotency_key},
        )
