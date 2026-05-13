from __future__ import annotations

from typing import Any

from trader.execution.gateway import ExecutionGateway
from trader.execution.models import (
    ExecutionEvent,
    ExecutionEventType,
    ExecutionReason,
    ExecutionResult,
    ExecutionSide,
    ExecutionStatus,
    GatewayCapabilities,
    GatewayCapability,
    GatewayMode,
    OrderIntent,
    ReconcileRequest,
    ReconcileResult,
    RiskIntent,
)
from trader.utils.operate import OperateType
from trader.utils.symbol_interval import Symbol

try:
    import backtrader as bt
except Exception:  # pragma: no cover - backtrader is a runtime dependency, this keeps import-time behavior defensive.
    bt = None


def _order_ids(payload: Any) -> list[str]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        ids = []
        for key in ("orderId", "order_id", "clientOrderId", "orderListId", "order_list_id"):
            if payload.get(key) is not None:
                ids.append(str(payload[key]))
        for key in ("orders", "orderReports", "order_reports"):
            for child in payload.get(key) or []:
                ids.extend(_order_ids(child))
        return ids
    if isinstance(payload, (list, tuple)):
        ids = []
        for item in payload:
            ids.extend(_order_ids(item))
        return ids
    ids = []
    for key in ("order_id", "orderId", "id", "order_list_id", "orderListId"):
        value = getattr(payload, key, None)
        if value is not None:
            ids.append(str(value))
            break
    for key in ("orders", "orderReports", "order_reports"):
        children = getattr(payload, key, None)
        if children:
            for child in children:
                ids.extend(_order_ids(child))
    return ids


def _symbol_arg(symbol: str):
    if "-" in symbol:
        return Symbol(symbol)
    quote_suffixes = ("USDT", "BUSD", "USDC", "BTC", "ETH")
    for quote in quote_suffixes:
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return Symbol(f"{symbol[: -len(quote)]}-{quote}")
    return Symbol(symbol)


def _accepted_order_result(
    *,
    gateway: GatewayMode,
    staged_execution_mode: str,
    intent: OrderIntent,
    status: ExecutionStatus,
    order_id: str | None,
    event_statuses: list[ExecutionStatus],
) -> ExecutionResult:
    events = [
        ExecutionEvent(
            event_type=_event_type_for_status(event_status),
            gateway=gateway,
            staged_execution_mode=staged_execution_mode,
            intent_id=intent.intent_id,
            operation_id=intent.operation_id,
            symbol=intent.symbol,
            order_id=order_id,
            trade_id=intent.trade_id,
            status=event_status,
            quantity=intent.quantity,
            price=intent.price,
            metadata=dict(intent.metadata),
        )
        for event_status in event_statuses
    ]
    return ExecutionResult.from_accepted(
        intent_id=intent.intent_id,
        operation_id=intent.operation_id,
        status=status,
        events=events,
        gateway_order_id=order_id,
    )


def _event_type_for_status(status: ExecutionStatus) -> ExecutionEventType:
    return {
        ExecutionStatus.SUBMITTED: ExecutionEventType.ORDER_SUBMITTED,
        ExecutionStatus.ACCEPTED: ExecutionEventType.ORDER_ACCEPTED,
        ExecutionStatus.FILLED: ExecutionEventType.ORDER_FILLED,
        ExecutionStatus.CANCELED: ExecutionEventType.ORDER_CANCELED,
        ExecutionStatus.REJECTED: ExecutionEventType.ORDER_REJECTED,
    }.get(status, ExecutionEventType.ORDER_REJECTED)


def _unsupported(intent_id: str, operation_id: str, capability: GatewayCapability, gateway: GatewayMode) -> ExecutionResult:
    return ExecutionResult.unsupported(intent_id=intent_id, operation_id=operation_id, capability=capability, gateway=gateway)


class BacktraderExecutionGateway(ExecutionGateway):
    def __init__(self, strategy, *, staged_execution_mode: str = "backtrader"):
        self.strategy = strategy
        self.staged_execution_mode = staged_execution_mode

    @property
    def capabilities(self) -> GatewayCapabilities:
        return GatewayCapabilities(
            gateway=GatewayMode.BACKTRADER,
            supported={
                GatewayCapability.MARKET_ENTRY,
                GatewayCapability.MARKET_CLOSE,
                GatewayCapability.PROTECTIVE_STOP,
                GatewayCapability.TAKE_PROFIT_LIMIT,
                GatewayCapability.OCO_PROTECTION,
                GatewayCapability.BREAKEVEN_REPLACEMENT,
                GatewayCapability.CANCEL_ORDER,
                GatewayCapability.RECONCILE,
            },
        )

    def open_position(self, intent: OrderIntent) -> ExecutionResult:
        order = self._submit_market(intent, opening=True)
        return _accepted_order_result(
            gateway=GatewayMode.BACKTRADER,
            staged_execution_mode=self.staged_execution_mode,
            intent=intent,
            status=ExecutionStatus.ACCEPTED,
            order_id=str(getattr(order, "ref", "")) if order is not None else None,
            event_statuses=[ExecutionStatus.SUBMITTED, ExecutionStatus.ACCEPTED],
        )

    def place_protection(self, intent: RiskIntent) -> ExecutionResult:
        orders = []
        close_side = "sell" if intent.side == ExecutionSide.LONG else "buy"
        oco_order = None
        if intent.stop_price is not None:
            oco_order = getattr(self.strategy, close_side)(
                size=intent.quantity,
                exectype=getattr(getattr(bt, "Order", None), "Stop", "stop"),
                price=float(intent.stop_price),
                tradeid=intent.trade_id,
                **{"chainer_role": "stop"},
            )
            orders.append(oco_order)
        if intent.take_profit_price is not None:
            orders.append(
                getattr(self.strategy, close_side)(
                    size=intent.quantity,
                    exectype=getattr(getattr(bt, "Order", None), "Limit", "limit"),
                    price=float(intent.take_profit_price),
                    tradeid=intent.trade_id,
                    oco=oco_order,
                    **{"chainer_role": "take_profit"},
                )
            )
        order_id = ",".join(str(getattr(order, "ref", "")) for order in orders if order is not None)
        return self._protection_result(intent, order_id=order_id, event_type=ExecutionEventType.PROTECTION_ARMED)

    def replace_protection(self, intent: RiskIntent) -> ExecutionResult:
        order = intent.replacement_of_order_id
        if order is not None:
            self.strategy.cancel(order)
        return self.place_protection(intent)

    def close_position(self, intent: OrderIntent) -> ExecutionResult:
        order = self._submit_market(intent, opening=False)
        return _accepted_order_result(
            gateway=GatewayMode.BACKTRADER,
            staged_execution_mode=self.staged_execution_mode,
            intent=intent,
            status=ExecutionStatus.ACCEPTED,
            order_id=str(getattr(order, "ref", "")) if order is not None else None,
            event_statuses=[ExecutionStatus.SUBMITTED, ExecutionStatus.ACCEPTED],
        )

    def cancel_order(self, intent: OrderIntent) -> ExecutionResult:
        order = intent.metadata.get("order") or intent.metadata.get("order_id")
        self.strategy.cancel(order)
        return _accepted_order_result(
            gateway=GatewayMode.BACKTRADER,
            staged_execution_mode=self.staged_execution_mode,
            intent=intent,
            status=ExecutionStatus.CANCELED,
            order_id=str(order) if order is not None else None,
            event_statuses=[ExecutionStatus.CANCELED],
        )

    def reconcile(self, request: ReconcileRequest) -> ReconcileResult:
        return ReconcileResult(request=request)

    def _submit_market(self, intent: OrderIntent, *, opening: bool):
        if opening:
            method = "buy" if intent.side == ExecutionSide.LONG else "sell"
        else:
            method = "sell" if intent.side == ExecutionSide.LONG else "buy"
        role = "entry" if opening else "exit"
        return getattr(self.strategy, method)(size=intent.quantity, tradeid=intent.trade_id, **{"chainer_role": role})

    def _protection_result(self, intent: RiskIntent, *, order_id: str, event_type: ExecutionEventType) -> ExecutionResult:
        event = ExecutionEvent(
            event_type=event_type,
            gateway=GatewayMode.BACKTRADER,
            staged_execution_mode=self.staged_execution_mode,
            intent_id=intent.intent_id,
            operation_id=intent.operation_id,
            symbol=intent.symbol,
            order_id=order_id,
            trade_id=intent.trade_id,
            status=ExecutionStatus.ACCEPTED,
            quantity=intent.quantity,
            price=intent.stop_price or intent.take_profit_price,
            metadata=dict(intent.metadata),
        )
        return ExecutionResult.from_accepted(
            intent_id=intent.intent_id,
            operation_id=intent.operation_id,
            status=ExecutionStatus.ACCEPTED,
            events=[event],
            gateway_order_id=order_id,
        )


class BinanceLiveExecutionGateway(ExecutionGateway):
    def __init__(self, exchange, *, staged_execution_mode: str = "full_live_auto"):
        self.exchange = exchange
        self.staged_execution_mode = staged_execution_mode

    @property
    def capabilities(self) -> GatewayCapabilities:
        supported = getattr(self.exchange, "supported_gateway_capabilities", None)
        if callable(supported):
            supported = set(supported())
        else:
            supported = {GatewayCapability.MARKET_ENTRY, GatewayCapability.MARKET_CLOSE, GatewayCapability.CANCEL_ORDER, GatewayCapability.RECONCILE}
            if hasattr(self.exchange, "new_stop_order"):
                supported.add(GatewayCapability.PROTECTIVE_STOP)
            if hasattr(self.exchange, "new_take_profit_order"):
                supported.add(GatewayCapability.TAKE_PROFIT_LIMIT)
            if hasattr(self.exchange, "new_oco_order"):
                supported.add(GatewayCapability.OCO_PROTECTION)
            if hasattr(self.exchange, "replace_stop_order"):
                supported.add(GatewayCapability.BREAKEVEN_REPLACEMENT)
        return GatewayCapabilities(
            gateway=GatewayMode.BINANCE_LIVE,
            supported=supported,
            native_protection=GatewayCapability.PROTECTIVE_STOP in supported or GatewayCapability.OCO_PROTECTION in supported,
            local_guardian=False,
        )

    def open_position(self, intent: OrderIntent) -> ExecutionResult:
        op = OperateType.BUY if intent.side == ExecutionSide.LONG else OperateType.SHORT
        return self._submit_market(intent, op)

    def place_protection(self, intent: RiskIntent) -> ExecutionResult:
        symbol = _symbol_arg(intent.symbol)
        side = self._protection_side(intent)
        if intent.stop_price is not None and intent.take_profit_price is not None:
            method = getattr(self.exchange, "new_oco_order", None)
            capability = GatewayCapability.OCO_PROTECTION
            if method is None:
                return _unsupported(intent.intent_id, intent.operation_id, capability, GatewayMode.BINANCE_LIVE)
            payload = method(symbol, side, intent.quantity, intent.stop_price, intent.take_profit_price)
        elif intent.stop_price is not None:
            method = getattr(self.exchange, "new_stop_order", None)
            capability = GatewayCapability.PROTECTIVE_STOP
            if method is None:
                return _unsupported(intent.intent_id, intent.operation_id, capability, GatewayMode.BINANCE_LIVE)
            payload = method(symbol, side, intent.quantity, intent.stop_price)
        else:
            method = getattr(self.exchange, "new_take_profit_order", None)
            capability = GatewayCapability.TAKE_PROFIT_LIMIT
            if method is None:
                return _unsupported(intent.intent_id, intent.operation_id, capability, GatewayMode.BINANCE_LIVE)
            payload = method(symbol, side, intent.quantity, intent.take_profit_price)
        return self._native_protection_result(intent, payload, event_type=ExecutionEventType.PROTECTION_ARMED)

    def replace_protection(self, intent: RiskIntent) -> ExecutionResult:
        method = getattr(self.exchange, "replace_stop_order", None)
        if method is None:
            return _unsupported(intent.intent_id, intent.operation_id, GatewayCapability.BREAKEVEN_REPLACEMENT, GatewayMode.BINANCE_LIVE)
        if not str(intent.replacement_of_order_id or "").strip():
            event = ExecutionEvent(
                event_type=ExecutionEventType.PROTECTION_MISSING,
                gateway=GatewayMode.BINANCE_LIVE,
                staged_execution_mode=self.staged_execution_mode,
                intent_id=intent.intent_id,
                operation_id=intent.operation_id,
                symbol=intent.symbol,
                trade_id=intent.trade_id,
                status=ExecutionStatus.FAILED,
                reason=ExecutionReason.PROTECTION_MISSING,
                quantity=intent.quantity,
                price=intent.stop_price,
                metadata={"native": True, "missing": "replacement_of_order_id"},
            )
            return ExecutionResult(
                intent_id=intent.intent_id,
                operation_id=intent.operation_id,
                status=ExecutionStatus.FAILED,
                reason=ExecutionReason.PROTECTION_MISSING,
                events=[event],
                metadata={"missing": "replacement_of_order_id"},
            )
        side = self._protection_side(intent)
        payload = method(_symbol_arg(intent.symbol), side, intent.replacement_of_order_id, intent.quantity, intent.stop_price)
        return self._native_protection_result(intent, payload, event_type=ExecutionEventType.PROTECTION_REPLACED)

    def close_position(self, intent: OrderIntent) -> ExecutionResult:
        op = OperateType.SELL if intent.side == ExecutionSide.LONG else OperateType.CLOSE
        return self._submit_market(intent, op)

    def cancel_order(self, intent: OrderIntent) -> ExecutionResult:
        order_id = str(intent.metadata.get("order_id") or "")
        method = getattr(self.exchange, "cancel_order", None) or getattr(self.exchange, "delete_order", None)
        if method is None:
            return _unsupported(intent.intent_id, intent.operation_id, GatewayCapability.CANCEL_ORDER, GatewayMode.BINANCE_LIVE)
        method(_symbol_arg(intent.symbol), order_id)
        return _accepted_order_result(
            gateway=GatewayMode.BINANCE_LIVE,
            staged_execution_mode=self.staged_execution_mode,
            intent=intent,
            status=ExecutionStatus.CANCELED,
            order_id=order_id,
            event_statuses=[ExecutionStatus.CANCELED],
        )

    def reconcile(self, request: ReconcileRequest) -> ReconcileResult:
        positions = getattr(self.exchange, "get_position_view", lambda symbol: [])(request.symbol) or []
        protections = getattr(self.exchange, "get_open_protection_orders", lambda symbol: [])(request.symbol) or []
        return ReconcileResult(request=request, positions=list(positions), protections=list(protections))

    def _submit_market(self, intent: OrderIntent, op: OperateType) -> ExecutionResult:
        payload = self.exchange.new_order(_symbol_arg(intent.symbol), op, intent.quantity)
        ids = _order_ids(payload)
        if not ids:
            event = ExecutionEvent(
                event_type=ExecutionEventType.ORDER_REJECTED,
                gateway=GatewayMode.BINANCE_LIVE,
                staged_execution_mode=self.staged_execution_mode,
                intent_id=intent.intent_id,
                operation_id=intent.operation_id,
                symbol=intent.symbol,
                trade_id=intent.trade_id,
                status=ExecutionStatus.FAILED,
                reason=ExecutionReason.GATEWAY_REJECTED,
                quantity=intent.quantity,
                price=intent.price,
                metadata={**dict(intent.metadata), "raw_payload": payload},
            )
            return ExecutionResult(
                intent_id=intent.intent_id,
                operation_id=intent.operation_id,
                status=ExecutionStatus.FAILED,
                reason=ExecutionReason.GATEWAY_REJECTED,
                events=[event],
                metadata={"raw_payload": payload},
            )
        order_id = ",".join(ids) if ids else None
        return _accepted_order_result(
            gateway=GatewayMode.BINANCE_LIVE,
            staged_execution_mode=self.staged_execution_mode,
            intent=intent,
            status=ExecutionStatus.SUBMITTED,
            order_id=order_id,
            event_statuses=[ExecutionStatus.SUBMITTED, ExecutionStatus.ACCEPTED],
        )

    def _native_protection_result(self, intent: RiskIntent, payload: Any, *, event_type: ExecutionEventType) -> ExecutionResult:
        ids = _order_ids(payload)
        if not ids or not self._verify_native_orders(intent.symbol, ids):
            event = ExecutionEvent(
                event_type=ExecutionEventType.PROTECTION_MISSING,
                gateway=GatewayMode.BINANCE_LIVE,
                staged_execution_mode=self.staged_execution_mode,
                intent_id=intent.intent_id,
                operation_id=intent.operation_id,
                symbol=intent.symbol,
                trade_id=intent.trade_id,
                status=ExecutionStatus.FAILED,
                reason=ExecutionReason.NATIVE_PROTECTION_UNVERIFIED,
                quantity=intent.quantity,
                price=intent.stop_price or intent.take_profit_price,
                metadata={"native": True, "raw_payload": payload},
            )
            return ExecutionResult(
                intent_id=intent.intent_id,
                operation_id=intent.operation_id,
                status=ExecutionStatus.FAILED,
                reason=ExecutionReason.NATIVE_PROTECTION_UNVERIFIED,
                events=[event],
                metadata={"raw_payload": payload},
            )
        order_id = ",".join(ids)
        event = ExecutionEvent(
            event_type=event_type,
            gateway=GatewayMode.BINANCE_LIVE,
            staged_execution_mode=self.staged_execution_mode,
            intent_id=intent.intent_id,
            operation_id=intent.operation_id,
            symbol=intent.symbol,
            order_id=order_id,
            trade_id=intent.trade_id,
            status=ExecutionStatus.ACCEPTED,
            quantity=intent.quantity,
            price=intent.stop_price or intent.take_profit_price,
            metadata={"native": True, "raw_payload": payload},
        )
        return ExecutionResult.from_accepted(
            intent_id=intent.intent_id,
            operation_id=intent.operation_id,
            status=ExecutionStatus.ACCEPTED,
            events=[event],
            gateway_order_id=order_id,
            metadata={"raw_payload": payload},
        )

    def _verify_native_orders(self, symbol: str, order_ids: list[str]) -> bool:
        verifier = getattr(self.exchange, "verify_order_ids", None)
        if verifier is None:
            return bool(order_ids)
        return bool(verifier(_symbol_arg(symbol), order_ids))

    def _protection_side(self, intent: RiskIntent) -> OperateType:
        return OperateType.SELL if intent.side == ExecutionSide.LONG else OperateType.BUY
