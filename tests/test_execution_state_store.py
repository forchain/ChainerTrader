import asyncio

from tortoise import Tortoise

from trader.database.config import build_tortoise_config
from trader.database.execution_state import ExecutionStateCol
from trader.execution import ExecutionSide, ExecutionStatus, GatewayMode, OrderIntent, ProtectionIntentType, RiskIntent
from trader.execution.state import ExecutionStateRecord


class _Log:
    def debug(self, *_args, **_kwargs):
        pass

    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


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
            gateway=GatewayMode.BINANCE_LIVE,
            staged_execution_mode="small_live_auto",
            status=ExecutionStatus.SUBMITTED,
            timestamp=1_714_281_600,
        )

        first = await store.reserve(record)
        duplicate = await store.reserve(
            record.with_updates(status=ExecutionStatus.ACCEPTED, exchange_order_id="should-not-overwrite", updated_at=1_714_281_601)
        )

        saved = await store.get_by_idempotency_key(intent.idempotency_key)
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
            gateway=GatewayMode.BINANCE_LIVE,
            staged_execution_mode="small_live_auto",
            status=ExecutionStatus.ACCEPTED,
            exchange_order_id="stop-123,tp-456",
            protection_id="protection-1",
            timestamp=1_714_281_700,
        )

        await store.save(record)

        active = await store.list_open_by_symbol("BTCUSDT")
        saved = active[0]
        assert saved.gateway == GatewayMode.BINANCE_LIVE
        assert saved.staged_execution_mode == "small_live_auto"
        assert saved.order_role == ProtectionIntentType.BRACKET.value
        assert saved.protection_id == "protection-1"
        assert saved.stop_price == 95000.0
        assert saved.take_profit_price == 110000.0
        assert saved.raw_payload["idempotency_key"] == risk.idempotency_key

    asyncio.run(_with_db(run))
