from __future__ import annotations

from trader.core.execution import (
    ExecutionEvent,
    ExecutionEventType,
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
from trader.core.execution.interfaces import ExecutionGateway
from trader.execution.gateway_common import accepted_order_result

try:
    import backtrader as bt
except Exception:  # pragma: no cover - backtrader is a runtime dependency, this keeps import-time behavior defensive.
    bt = None


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
        return accepted_order_result(
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
        return accepted_order_result(
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
        return accepted_order_result(
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
