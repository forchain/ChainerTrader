import asyncio

from trader.execution import ExecutionResult, ExecutionSide, ExecutionStatus, GatewayMode, OrderIntentType, ProtectionIntentType
from trader.execution.gateways import BinanceLiveExecutionGateway
from trader.execution.state import ExecutionStateReservation
from trader.strategy.execution_kernel import (
    ExecutionOrchestrator,
    LegacyStrategyExecutionAdapter,
    RiskEngine,
    TradeLifecycleEngine,
    TradeLifecycleStatus,
)
from trader.utils.operate import Operate, OperateType


def test_trade_lifecycle_engine_transitions_from_execution_results():
    engine = TradeLifecycleEngine()
    entry = LegacyStrategyExecutionAdapter(symbol="BTCUSDT", default_quantity=0.25).order_intent_from_operation(
        _op(OperateType.BUY, signal_event_id="entry-signal"),
        trade_id="trade-1",
    )
    close = LegacyStrategyExecutionAdapter(symbol="BTCUSDT", default_quantity=0.25).order_intent_from_operation(
        _op(OperateType.SELL, signal_event_id="exit-signal"),
        trade_id="trade-1",
    )

    assert engine.apply_execution_result(TradeLifecycleStatus.OPENING, entry, _result(ExecutionStatus.FILLED)) == TradeLifecycleStatus.ACTIVE
    assert engine.apply_execution_result(TradeLifecycleStatus.CLOSING, close, _result(ExecutionStatus.FILLED)) == TradeLifecycleStatus.CLOSED
    assert engine.apply_execution_result(TradeLifecycleStatus.ACTIVE, close, _result(ExecutionStatus.REJECTED)) == TradeLifecycleStatus.ACTIVE


def test_risk_engine_builds_protection_and_breakeven_intents_from_signal_context():
    adapter = LegacyStrategyExecutionAdapter(symbol="BTCUSDT", default_quantity=0.25)
    entry = adapter.order_intent_from_operation(_op(OperateType.BUY, signal_event_id="entry-signal"), trade_id="trade-1")
    risk = RiskEngine()

    protection = risk.protection_for_entry(
        entry,
        stop_price=95000.0,
        take_profit_price=110000.0,
        metadata={"risk_reward_ratio": 2.0},
    )
    replacement = risk.breakeven_replacement(
        entry,
        stop_price=100000.0,
        replacement_of_order_id="stop-1",
        metadata={"breakeven_step": 1},
    )

    assert protection.protection_type == ProtectionIntentType.BRACKET
    assert protection.signal_event_id == "entry-signal"
    assert protection.metadata["risk_reward_ratio"] == 2.0
    assert replacement.protection_type == ProtectionIntentType.REPLACE_STOP
    assert replacement.stop_price == 100000.0


def test_legacy_strategy_adapter_routes_operations_to_portable_intents_with_metadata():
    adapter = LegacyStrategyExecutionAdapter(symbol="BTCUSDT", default_quantity=0.25)
    op = _op(OperateType.BUY, signal_event_id="signal-1")
    op.signal_metadata = {"suggested_stop_price": 95000.0}
    op.framework_trade = {"trade_id": "trade-1", "direction": "LONG", "take_profit": 110000.0}

    order = adapter.order_intent_from_operation(op, trade_id="trade-1")
    risk = adapter.risk_intent_from_operation(op, trade_id="trade-1", side=ExecutionSide.LONG)

    assert order.intent_type == OrderIntentType.ENTRY
    assert order.side == ExecutionSide.LONG
    assert order.signal_event_id == "signal-1"
    assert order.metadata["signal_metadata"]["suggested_stop_price"] == 95000.0
    assert risk.protection_type == ProtectionIntentType.BRACKET
    assert risk.stop_price == 95000.0
    assert risk.take_profit_price == 110000.0

    close_short = adapter.order_intent_from_operation(_op(OperateType.CLOSE, signal_event_id="close-short"), trade_id="trade-2")
    assert close_short.intent_type == OrderIntentType.CLOSE
    assert close_short.side == ExecutionSide.SHORT


def test_execution_orchestrator_reserves_state_before_gateway_submission():
    async def run():
        gateway = BinanceLiveExecutionGateway(FakeExchange())
        store = MemoryStateStore()
        orchestrator = ExecutionOrchestrator(
            gateway,
            gateway_mode=GatewayMode.BINANCE_LIVE,
            staged_execution_mode="small_live_auto",
            state_store=store,
            clock=lambda: 1_714_281_600,
        )
        intent = LegacyStrategyExecutionAdapter(symbol="BTCUSDT", default_quantity=0.25).order_intent_from_operation(
            _op(OperateType.BUY, signal_event_id="entry-signal"),
            trade_id="trade-1",
        )

        first = await orchestrator.execute_order(intent)
        duplicate = await orchestrator.execute_order(intent)

        assert first.status == ExecutionStatus.SUBMITTED
        assert duplicate.status == ExecutionStatus.SKIPPED
        assert len(store.records) == 1
        assert store.records[intent.idempotency_key].status == ExecutionStatus.SUBMITTED
        assert store.records[intent.idempotency_key].exchange_order_id == "live-order-1"

    asyncio.run(run())


class MemoryStateStore:
    def __init__(self):
        self.records = {}

    async def reserve(self, record):
        existing = self.records.get(record.idempotency_key)
        if existing is not None:
            return ExecutionStateReservation(existing, created=False)
        self.records[record.idempotency_key] = record
        return ExecutionStateReservation(record, created=True)

    async def save(self, record):
        self.records[record.idempotency_key] = record
        return record


class FakeExchange:
    def new_order(self, symbol, op, quantity):
        return {"orderId": "live-order-1"}


def _op(otype, *, signal_event_id):
    op = Operate(otype, 1_714_281_600, 100000.0)
    op.signal_event_id = signal_event_id
    return op


def _result(status):
    return ExecutionResult(intent_id="intent", operation_id="op", status=status)
