from trader.live.dashboard import (
    build_macd_divergence_event,
    build_risk_overlay_events,
    build_signal_marker_event,
    kline_to_chart_candle,
    kline_update_event,
    strategy_execution_event,
)
from trader.live.market_data import KlineUpdate
from trader.utils.kline import Kline
from trader.utils.operate import Operate, OperateType

BASE = 1_714_281_600


def test_kline_to_chart_candle_uses_tradingview_ready_shape():
    candle = kline_to_chart_candle(Kline(BASE, 100, 105, 99, 102, BASE + 59, 12.5, 0, 0, 0, 0))

    assert candle == {
        "time": BASE,
        "time_text": "2024-04-28 13:20:00",
        "open": 100.0,
        "high": 105.0,
        "low": 99.0,
        "close": 102.0,
        "volume": 12.5,
    }


def test_kline_update_event_adds_text_for_event_and_candle_times():
    update = KlineUpdate(
        exchange="BINANCE",
        symbol="BTCUSDT",
        interval="1m",
        open_time=BASE,
        close_time=BASE + 59,
        open=100,
        high=105,
        low=99,
        close=102,
        volume=12.5,
        event_time=BASE + 30,
        is_closed=True,
    )

    event = kline_update_event(strategy_id=7, update=update)

    assert event.event_time == BASE + 30
    assert event.payload["event_time_text"] == "2024-04-28 13:20:30"
    assert event.payload["candle"]["time"] == BASE
    assert event.payload["candle"]["time_text"] == "2024-04-28 13:20:00"
    assert event.payload["candle"]["close_time_text"] == "2024-04-28 13:20:59"


def test_strategy_execution_event_adds_text_time_to_operations():
    op = Operate(OperateType.BUY, BASE, 101.5)
    result = type("Result", (), {"opts": [op]})()

    event = strategy_execution_event(strategy_id=7, event_time=BASE + 60, result=result)

    assert event.payload["event_time_text"] == "2024-04-28 13:21:00"
    assert event.payload["operations"] == [
        {
            "type": "BUY",
            "datetime": BASE,
            "datetime_text": "2024-04-28 13:20:00",
            "price": 101.5,
        }
    ]


def test_signal_marker_event_contains_chart_lookup_fields():
    op = Operate(OperateType.LONG, BASE, 101.5)
    op.signal_event_id = "macd-triple-1"
    op.trigger_reason = "signal_entry"

    event = build_signal_marker_event(strategy_id=7, op=op, mode="manual_notify")

    assert event.event_type == "signal_marker"
    assert event.strategy_id == 7
    assert event.payload["time"] == BASE
    assert event.payload["price"] == 101.5
    assert event.payload["side"] == "LONG"
    assert event.payload["mode"] == "manual_notify"
    assert event.payload["signal_event_id"] == "macd-triple-1"
    assert event.payload["signal_number"] == 1
    assert event.payload["time_text"] == "2024-04-28 13:20:00"


def test_signal_marker_event_generates_stable_id_when_strategy_does_not_provide_one():
    op = Operate(OperateType.BUY, BASE, 101.5)

    event = build_signal_marker_event(strategy_id=7, op=op, mode="manual_notify", signal_number=3)

    assert event.payload["signal_number"] == 3
    assert event.payload["signal_event_id"] == "live-7-1714281600-BUY-3"
    assert getattr(op, "signal_event_id") == "live-7-1714281600-BUY-3"
    assert getattr(op, "signal_number") == 3


def test_risk_overlay_events_include_stop_take_profit_and_breakeven_movement():
    op = Operate(OperateType.LONG, BASE, 101.5)
    op.stop_loss = 97.0
    op.take_profit = 110.0
    op.risk_reward_ratio = 2.0
    op.breakeven_old_stop = 97.0
    op.breakeven_new_stop = 101.5
    op.breakeven_step = 1

    events = build_risk_overlay_events(strategy_id=7, op=op)

    assert [event.event_type for event in events] == ["risk_overlay", "risk_overlay", "risk_overlay"]
    assert events[0].payload["overlay_type"] == "stop_loss"
    assert events[0].payload["price"] == 97.0
    assert events[0].payload["source"] == "local_strategy_reference"
    assert events[1].payload["overlay_type"] == "take_profit"
    assert events[1].payload["risk_reward_ratio"] == 2.0
    assert events[2].payload["overlay_type"] == "breakeven_move"
    assert events[2].payload["old_stop"] == 97.0
    assert events[2].payload["new_stop"] == 101.5
    assert events[2].payload["step"] == 1


def test_risk_overlay_events_infer_stop_loss_from_signal_metadata():
    op = Operate(OperateType.LONG, BASE, 101.5)
    op.signal_metadata = {"suggested_stop_price": 97.0}

    events = build_risk_overlay_events(strategy_id=7, op=op)

    assert len(events) == 1
    assert events[0].payload["overlay_type"] == "stop_loss"
    assert events[0].payload["price"] == 97.0
    assert events[0].payload["source"] == "signal_metadata"


def test_risk_overlay_events_use_framework_trade_context_stop_and_take_profit():
    op = Operate(OperateType.LONG, BASE, 101.5)
    op.framework_trade = {
        "initial_stop_price": 97.0,
        "stop_price": 98.0,
        "take_profit": 110.0,
        "risk_reward_ratio": 2.0,
    }

    events = build_risk_overlay_events(strategy_id=7, op=op)

    assert [event.payload["overlay_type"] for event in events] == ["stop_loss", "take_profit"]
    assert events[0].payload["price"] == 98.0
    assert events[0].payload["initial_price"] == 97.0
    assert events[0].payload["source"] == "framework_trade_context"
    assert events[1].payload["price"] == 110.0
    assert events[1].payload["risk_reward_ratio"] == 2.0


def test_macd_divergence_event_preserves_stable_event_id_and_conditions():
    metadata = {
        "signal_event_id": "macd-triple-1",
        "direction": "LONG",
        "legs": [{"price_time": BASE - 120, "macd_time": BASE - 120}, {"price_time": BASE, "macd_time": BASE}],
        "conditions": {"price_divergence": True, "macd_divergence": True},
    }

    event = build_macd_divergence_event(strategy_id=7, event_time=BASE, metadata=metadata)

    assert event.event_type == "macd_divergence"
    assert event.event_time == BASE
    assert event.payload["signal_event_id"] == "macd-triple-1"
    assert event.payload["direction"] == "LONG"
    assert event.payload["legs"] == metadata["legs"]
    assert event.payload["conditions"]["price_divergence"] is True
