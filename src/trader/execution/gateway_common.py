from __future__ import annotations

from trader.core.execution import ExecutionEvent, ExecutionEventType, ExecutionResult, ExecutionStatus, GatewayMode, OrderIntent


def accepted_order_result(
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
            event_type=event_type_for_status(event_status),
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


def event_type_for_status(status: ExecutionStatus) -> ExecutionEventType:
    return {
        ExecutionStatus.SUBMITTED: ExecutionEventType.ORDER_SUBMITTED,
        ExecutionStatus.ACCEPTED: ExecutionEventType.ORDER_ACCEPTED,
        ExecutionStatus.FILLED: ExecutionEventType.ORDER_FILLED,
        ExecutionStatus.CANCELED: ExecutionEventType.ORDER_CANCELED,
        ExecutionStatus.REJECTED: ExecutionEventType.ORDER_REJECTED,
    }.get(status, ExecutionEventType.ORDER_REJECTED)
