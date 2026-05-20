from __future__ import annotations

from logging import Logger

from trader.database.models import ExecutionStateModel
from trader.execution.models import ExecutionStatus
from trader.execution.state import ExecutionStateRecord, ExecutionStateReservation

TERMINAL_STATUSES = {
    ExecutionStatus.CANCELED.value,
    ExecutionStatus.REJECTED.value,
    ExecutionStatus.SKIPPED.value,
    ExecutionStatus.FAILED.value,
}


def model_to_execution_state(row: ExecutionStateModel) -> ExecutionStateRecord:
    return ExecutionStateRecord(
        idempotency_key=row.idempotency_key,
        intent_id=row.intent_id,
        operation_id=row.operation_id,
        gateway=row.gateway,
        staged_execution_mode=row.staged_execution_mode,
        symbol=row.symbol,
        trade_id=row.trade_id,
        order_role=row.order_role,
        status=row.status,
        exchange_order_id=row.exchange_order_id,
        protection_id=row.protection_id,
        quantity=row.quantity,
        price=row.price,
        stop_price=row.stop_price,
        take_profit_price=row.take_profit_price,
        raw_payload=dict(row.raw_payload or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
        task_id=row.task_id,
    )


class ExecutionStateCol:
    def __init__(self, log: Logger):
        self.log = log

    async def reserve(self, record: ExecutionStateRecord) -> ExecutionStateReservation:
        existing = await self.get_by_idempotency_key(record.idempotency_key)
        if existing is not None:
            return ExecutionStateReservation(existing, created=False)
        saved = await self.save(record)
        return ExecutionStateReservation(saved, created=True)

    async def save(self, record: ExecutionStateRecord) -> ExecutionStateRecord:
        await ExecutionStateModel.update_or_create(
            idempotency_key=record.idempotency_key,
            defaults={
                "intent_id": record.intent_id,
                "operation_id": record.operation_id,
                "gateway": record.gateway.value,
                "staged_execution_mode": record.staged_execution_mode,
                "symbol": record.symbol,
                "trade_id": record.trade_id,
                "order_role": record.order_role,
                "status": record.status.value,
                "exchange_order_id": record.exchange_order_id,
                "protection_id": record.protection_id,
                "quantity": record.quantity,
                "price": record.price,
                "stop_price": record.stop_price,
                "take_profit_price": record.take_profit_price,
                "raw_payload": dict(record.raw_payload),
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "task_id": record.task_id,
            },
        )
        saved = await self.get_by_idempotency_key(record.idempotency_key)
        if saved is None:
            raise RuntimeError(f"execution state save failed for {record.idempotency_key}")
        return saved

    async def get_by_idempotency_key(self, idempotency_key: str) -> ExecutionStateRecord | None:
        row = await ExecutionStateModel.filter(idempotency_key=idempotency_key).first()
        if row is None:
            return None
        return model_to_execution_state(row)

    async def list_open_by_symbol(self, symbol: str) -> list[ExecutionStateRecord]:
        rows = await ExecutionStateModel.filter(symbol=symbol).exclude(status__in=TERMINAL_STATUSES).order_by("created_at", "id")
        return [model_to_execution_state(row) for row in rows]

    async def list_open_by_task(self, task_id: int) -> list[ExecutionStateRecord]:
        rows = (
            await ExecutionStateModel.filter(task_id=task_id)
            .exclude(status__in=TERMINAL_STATUSES)
            .order_by("created_at", "id")
        )
        return [model_to_execution_state(row) for row in rows]
