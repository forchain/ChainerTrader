import asyncio

from tortoise import Tortoise

from trader.database.config import build_tortoise_config
from trader.database.execution_state import ExecutionStateCol
from trader.database.models import ExecutionStateModel
from trader.execution import ExecutionSide, ExecutionStatus, GatewayMode, OrderIntent, ProtectionIntentType, RiskIntent
from trader.execution.state import ExecutionStateRecord


class _Log:
    def __init__(self):
        self.errors = []

    def debug(self, *_args, **_kwargs):
        pass

    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, msg, *_args, **_kwargs):
        self.errors.append(msg)


async def _with_db(fn):
    await Tortoise.init(config=build_tortoise_config("sqlite://:memory:"))
    await Tortoise.generate_schemas()
    try:
        await fn()
    finally:
        await Tortoise.close_connections()


def test_execution_state_store_reserves_idempotency_key_before_order_submit():
    async def run():
        store = ExecutionStateCol(_Log())
        intent = OrderIntent.entry(
            intent_id="intent-1",
            operation_id="op-1",
            symbol="BTCUSDT",
            side=ExecutionSide.LONG,
            quantity=0.25,
            notional=25000.0,
            trade_id="trade-1",
        )
        record = ExecutionStateRecord.from_order_intent(
            intent,
            task_id=11,
            gateway=GatewayMode.BINANCE_LIVE,
            staged_execution_mode="auto_trade",
            status=ExecutionStatus.SUBMITTED,
            timestamp=1_714_281_600,
        )

        first = await store.reserve(record)
        duplicate = await store.reserve(
            record.with_updates(status=ExecutionStatus.ACCEPTED, exchange_order_id="should-not-overwrite", updated_at=1_714_281_601)
        )

        saved = await store.get_by_idempotency_key(record.idempotency_key)
        assert first.created is True
        assert duplicate.created is False
        assert saved.intent_id == "intent-1"
        assert saved.exchange_order_id is None
        assert saved.status == ExecutionStatus.SUBMITTED

        updated = await store.save(
            saved.with_updates(status=ExecutionStatus.ACCEPTED, exchange_order_id="live-order-1", updated_at=1_714_281_602)
        )

        assert updated.exchange_order_id == "live-order-1"
        assert updated.status == ExecutionStatus.ACCEPTED

    asyncio.run(_with_db(run))


def test_execution_state_store_persists_protection_state_for_reconciliation():
    async def run():
        store = ExecutionStateCol(_Log())
        risk = RiskIntent.place_protection(
            intent_id="risk-1",
            operation_id="op-1",
            symbol="BTCUSDT",
            side=ExecutionSide.LONG,
            trade_id="trade-1",
            quantity=0.25,
            stop_price=95000.0,
            take_profit_price=110000.0,
        )
        record = ExecutionStateRecord.from_risk_intent(
            risk,
            task_id=22,
            gateway=GatewayMode.BINANCE_LIVE,
            staged_execution_mode="auto_trade",
            status=ExecutionStatus.ACCEPTED,
            exchange_order_id="stop-123,tp-456",
            protection_id="protection-1",
            timestamp=1_714_281_700,
        )

        await store.save(record)

        active = await store.list_open_by_symbol("BTCUSDT")
        saved = active[0]
        assert saved.gateway == GatewayMode.BINANCE_LIVE
        assert saved.staged_execution_mode == "auto_trade"
        assert saved.order_role == ProtectionIntentType.BRACKET.value
        assert saved.protection_id == "protection-1"
        assert saved.stop_price == 95000.0
        assert saved.take_profit_price == 110000.0
        assert saved.raw_payload["idempotency_key"] == risk.idempotency_key
        assert saved.task_id == 22

        active_by_task = await store.list_open_by_task(22)
        assert len(active_by_task) == 1
        assert active_by_task[0].idempotency_key == record.idempotency_key

        assert await store.list_open_by_task(9999) == []

    asyncio.run(_with_db(run))


def test_execution_state_store_keeps_matching_intents_from_different_tasks():
    async def run():
        store = ExecutionStateCol(_Log())
        intent = OrderIntent.entry(
            intent_id="intent:1",
            operation_id="1",
            symbol="BTCUSDT",
            side=ExecutionSide.LONG,
            quantity=0.25,
            trade_id="1",
        )
        first = ExecutionStateRecord.from_order_intent(
            intent,
            task_id=101,
            gateway=GatewayMode.BINANCE_LIVE,
            staged_execution_mode="auto_trade",
            status=ExecutionStatus.SUBMITTED,
            exchange_order_id="first-order",
            timestamp=1_714_281_800,
        )
        second = ExecutionStateRecord.from_order_intent(
            intent,
            task_id=202,
            gateway=GatewayMode.BINANCE_LIVE,
            staged_execution_mode="auto_trade",
            status=ExecutionStatus.SUBMITTED,
            exchange_order_id="second-order",
            timestamp=1_714_281_801,
        )

        await store.save(first)
        await store.save(second)

        assert first.idempotency_key != second.idempotency_key
        assert (await store.get_by_idempotency_key(first.idempotency_key)).exchange_order_id == "first-order"
        assert (await store.get_by_idempotency_key(second.idempotency_key)).exchange_order_id == "second-order"

    asyncio.run(_with_db(run))


def test_execution_state_store_updates_without_update_or_create_instance_save_path():
    async def run():
        store = ExecutionStateCol(_Log())
        intent = OrderIntent.entry(
            intent_id="intent-ctx",
            operation_id="op-ctx",
            symbol="BTCUSDT",
            side=ExecutionSide.LONG,
            quantity=0.25,
            trade_id="trade-ctx",
        )
        record = ExecutionStateRecord.from_order_intent(
            intent,
            task_id=33,
            gateway=GatewayMode.BINANCE_LIVE,
            staged_execution_mode="auto_trade",
            status=ExecutionStatus.SUBMITTED,
            exchange_order_id="live-order-ctx",
            timestamp=1_714_281_800,
        )

        await store.save(record)

        async def fail_update_or_create(**_kwargs):
            raise AssertionError("save should not use update_or_create")

        original = ExecutionStateModel.update_or_create
        ExecutionStateModel.update_or_create = fail_update_or_create
        try:
            updated = await store.save(
                record.with_updates(status=ExecutionStatus.FAILED, exchange_order_id=None, updated_at=1_714_281_801)
            )
        finally:
            ExecutionStateModel.update_or_create = original

        assert updated.status == ExecutionStatus.FAILED
        assert updated.exchange_order_id is None
        assert store.log.errors == []

    asyncio.run(_with_db(run))


def test_execution_state_store_logs_context_when_save_fails():
    async def run():
        store = ExecutionStateCol(_Log())
        intent = OrderIntent.entry(
            intent_id="intent-ctx",
            operation_id="op-ctx",
            symbol="BTCUSDT",
            side=ExecutionSide.LONG,
            quantity=0.25,
            trade_id="trade-ctx",
        )
        record = ExecutionStateRecord.from_order_intent(
            intent,
            task_id=33,
            gateway=GatewayMode.BINANCE_LIVE,
            staged_execution_mode="auto_trade",
            status=ExecutionStatus.SUBMITTED,
            exchange_order_id="live-order-ctx",
            timestamp=1_714_281_800,
        )

        original_filter = ExecutionStateModel.filter

        def fail_filter(*_args, **_kwargs):
            raise RuntimeError("boom")

        ExecutionStateModel.filter = fail_filter
        try:
            try:
                await store.save(record)
            except RuntimeError as exc:
                assert str(exc) == "boom"
        finally:
            ExecutionStateModel.filter = original_filter

        assert len(store.log.errors) == 1
        assert "execution state save failed" in store.log.errors[0]
        assert "task_id=33" in store.log.errors[0]
        assert "idempotency_key=" in store.log.errors[0]
        assert "order_id=live-order-ctx" in store.log.errors[0]

    asyncio.run(_with_db(run))
