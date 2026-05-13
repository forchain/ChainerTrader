import os
from types import SimpleNamespace

import pytest

from trader.execution import ExecutionEventType, ExecutionReason, ExecutionSide, ExecutionStatus
from trader.execution.gateways import BacktraderExecutionGateway, BinanceLiveExecutionGateway
from trader.strategy.execution_kernel import LegacyStrategyExecutionAdapter
from trader.utils.operate import Operate, OperateType


class FakeBacktraderStrategy:
    def __init__(self):
        self.calls = []

    def buy(self, **kwargs):
        order = SimpleNamespace(ref=f"bt-{len(self.calls) + 1}")
        self.calls.append(("buy", kwargs))
        return order

    def sell(self, **kwargs):
        order = SimpleNamespace(ref=f"bt-{len(self.calls) + 1}")
        self.calls.append(("sell", kwargs))
        return order

    def cancel(self, order):
        self.calls.append(("cancel", order))


def test_macd_triple_divergence_flow_has_portable_backtrader_and_live_gateway_events():
    adapter = LegacyStrategyExecutionAdapter(symbol="BTCUSDT", default_quantity=0.25)
    entry_op = Operate(OperateType.BUY, 1_714_281_600, 100000.0)
    entry_op.signal_event_id = "macd-triple-divergence-signal-1"
    entry_op.signal_metadata = {"strategy": "macd_triple_divergence", "suggested_stop_price": 95000.0}
    entry_op.framework_trade = {
        "trade_id": "trade-1",
        "direction": "LONG",
        "stop_price": 95000.0,
        "take_profit": 110000.0,
        "risk_reward_ratio": 2.0,
    }
    breakeven_op = Operate(OperateType.RISK_UPDATE, 1_714_281_660, 100000.0)
    breakeven_op.signal_event_id = "macd-triple-divergence-signal-1-breakeven"
    breakeven_op.framework_trade = {"trade_id": "trade-1", "direction": "LONG"}
    breakeven_op.protection_order_id = "stop-1"
    breakeven_op.breakeven_new_stop = 100000.0
    close_op = Operate(OperateType.SELL, 1_714_281_720, 109000.0)
    close_op.signal_event_id = "macd-triple-divergence-signal-1-close"
    close_op.framework_trade = {"trade_id": "trade-1", "direction": "LONG"}

    entry = adapter.order_intent_from_operation(entry_op, trade_id="trade-1")
    protection = adapter.risk_intent_from_operation(entry_op, trade_id="trade-1", side=ExecutionSide.LONG)
    breakeven = adapter.risk_intent_from_operation(breakeven_op, trade_id="trade-1", side=ExecutionSide.LONG)
    close = adapter.order_intent_from_operation(close_op, trade_id="trade-1")

    backtrader = BacktraderExecutionGateway(FakeBacktraderStrategy())
    live = BinanceLiveExecutionGateway(FakeLiveExchange())

    backtrader_entry = backtrader.open_position(entry)
    live_entry = live.open_position(entry)
    backtrader_protection = backtrader.place_protection(protection)
    live_protection = live.place_protection(protection)
    live_breakeven = live.replace_protection(breakeven)
    backtrader_close = backtrader.close_position(close)
    live_close = live.close_position(close)

    assert [event.event_type for event in live_entry.events] == [event.event_type for event in backtrader_entry.events]
    assert live_protection.events[-1].event_type == backtrader_protection.events[-1].event_type == ExecutionEventType.PROTECTION_ARMED
    assert live_breakeven.events[-1].event_type == ExecutionEventType.PROTECTION_REPLACED
    assert [event.event_type for event in live_close.events] == [event.event_type for event in backtrader_close.events]


class FakeLiveExchange:
    def new_order(self, symbol, op, quantity):
        return {"orderId": "live-order-1"}

    def new_oco_order(self, symbol, side, quantity, stop_price, take_profit_price):
        return {"orders": [{"orderId": "stop-1"}, {"orderId": "tp-1"}]}

    def replace_stop_order(self, symbol, side, order_id, quantity, stop_price):
        if not order_id:
            raise AssertionError("replace_stop_order must not be called without an order_id")
        return {"orderId": "stop-2"}


def test_live_gateway_rejects_breakeven_replace_without_existing_protection_order_id():
    adapter = LegacyStrategyExecutionAdapter(symbol="BTCUSDT", default_quantity=0.25)
    breakeven_op = Operate(OperateType.RISK_UPDATE, 1_714_281_660, 100000.0)
    breakeven_op.signal_event_id = "macd-triple-divergence-signal-1-breakeven"
    breakeven_op.framework_trade = {"trade_id": "trade-1", "direction": "LONG"}
    breakeven_op.breakeven_new_stop = 100000.0

    breakeven = adapter.risk_intent_from_operation(breakeven_op, trade_id="trade-1", side=ExecutionSide.LONG)
    result = BinanceLiveExecutionGateway(FakeLiveExchange()).replace_protection(breakeven)

    assert result.status == ExecutionStatus.FAILED
    assert result.reason == ExecutionReason.PROTECTION_MISSING
    assert result.gateway_order_id is None


@pytest.mark.skipif(os.getenv("CHAINERTRADER_ENABLE_SMALL_LIVE_SMOKE") != "1", reason="small live smoke requires explicit opt-in")
def test_small_live_gateway_smoke_requires_explicit_credentials_and_notional_cap():
    missing = [
        name
        for name in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "CHAINERTRADER_SMALL_LIVE_MAX_NOTIONAL")
        if not os.getenv(name)
    ]
    if missing:
        pytest.skip(f"small live smoke credentials/config missing: {', '.join(missing)}")

    max_notional = float(os.environ["CHAINERTRADER_SMALL_LIVE_MAX_NOTIONAL"])
    assert max_notional > 0
    assert max_notional <= float(os.getenv("CHAINERTRADER_SMALL_LIVE_HARD_LIMIT", "25"))
    assert BinanceLiveExecutionGateway is not None
