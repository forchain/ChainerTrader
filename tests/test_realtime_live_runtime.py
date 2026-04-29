from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from trader.common.config import Config
from trader.live.market_data import normalize_binance_kline_message
from trader.live.runtime import RealtimeLiveStrategyRuntime
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.utils.kline import Kline
from trader.utils.operate import Operate, OperateType
from trader.utils.symbol_interval import Interval, SymbolInterval

BASE = 1_714_281_600


@pytest.fixture
def anyio_backend():
    return "asyncio"


@dataclass
class StrategyResult:
    opts: list


class FakeKlineStore:
    def __init__(self, latest=None, latest_window=None):
        self.latest = latest
        self.latest_window = latest_window or []
        self.added = []

    def get_latest_kline(self, name):
        return self.latest

    def add_klines(self, name, klines):
        self.added.append((name, list(klines)))
        self.latest_window.extend(klines)
        if klines:
            self.latest = klines[-1]
        return len(klines)

    def get_latest_klines(self, name, limit):
        return self.latest_window[-limit:]


class FakeDb:
    def __init__(self, kline_store, previous_result=None):
        self.kline = kline_store
        self.task = SimpleNamespace(get_task=lambda task_id: SimpleNamespace(tret=previous_result) if previous_result else None)


class FakeExchange:
    def __init__(self, fetched):
        self.fetched = fetched
        self.latest_requests = []
        self.range_requests = []
        self.new_order_calls = []

    def get_latest_klines(self, si, limit):
        self.latest_requests.append((si.name(), limit))
        return self.fetched[-limit:]

    def get_klines(self, si, start_time=None, end_time=None, limit=500):
        self.range_requests.append((si.name(), start_time, end_time, limit))
        return [kl for kl in self.fetched if start_time <= kl.open_time <= end_time][:limit]

    def new_order(self, *args, **kwargs):
        self.new_order_calls.append((args, kwargs))
        raise AssertionError("realtime manual_notify runtime must not place exchange orders")


class Recorder:
    def __init__(self):
        self.executions = []
        self.notifications = []
        self.events = []

    def run_strategy(self, candles):
        self.executions.append(list(candles))
        if not candles:
            return None
        return StrategyResult([Operate(OperateType.BUY, candles[-1].open_time, candles[-1].close)])

    def notify(self, result):
        self.notifications.append(result)
        return ["manual-event"]

    async def publish(self, event):
        self.events.append(event)


class HistoryMergingRecorder(Recorder):
    def __init__(self, historical_op):
        super().__init__()
        self.historical_op = historical_op

    def notify(self, result):
        result.opts = [self.historical_op] + list(result.opts or [])
        return super().notify(result)


class WindowReplayRecorder(Recorder):
    def run_strategy(self, candles):
        self.executions.append(list(candles))
        if not candles:
            return None
        latest_time = candles[-1].open_time
        ops = [
            Operate(OperateType.BUY, BASE, 100.0),
            Operate(OperateType.CLOSE, BASE + 60, 101.0),
        ]
        if latest_time >= BASE + 120:
            ops.append(Operate(OperateType.SELL, BASE + 120, 102.0))
        return StrategyResult(ops)


def _kline(open_time, close=100.0):
    return Kline(open_time, close - 1, close + 1, close - 2, close, open_time + 59, 10, 1000, 10, 5, 500)


def _task_config():
    return TaskConfig(
        id=99,
        ttype=TaskType.TRADER,
        symbol_interval=SymbolInterval("BTC-USDT", Interval.INTERVAL_1m),
        strategies=["macd_triple_divergence"],
        free=1000,
        live_execution_mode="manual_notify",
    )


def _payload(open_time, closed):
    return normalize_binance_kline_message(
        {
            "e": "kline",
            "E": (open_time + 5) * 1000,
            "s": "BTCUSDT",
            "k": {
                "t": open_time * 1000,
                "T": (open_time + 59) * 1000 + 999,
                "s": "BTCUSDT",
                "i": "1m",
                "o": "100",
                "c": "101",
                "h": "102",
                "l": "99",
                "v": "1",
                "n": 1,
                "x": closed,
            },
        }
    )


@pytest.mark.anyio
async def test_realtime_runtime_startup_backfills_latest_500_and_executes_once():
    fetched = [_kline(BASE + i * 60, close=100 + i) for i in range(500)]
    kline_store = FakeKlineStore()
    recorder = Recorder()
    runtime = RealtimeLiveStrategyRuntime(
        _task_config(),
        Config(window=500),
        db_manager=FakeDb(kline_store),
        exchange=FakeExchange(fetched),
        strategy_runner=recorder.run_strategy,
        notification_handler=recorder.notify,
        event_publisher=recorder.publish,
        now_fn=lambda: BASE + 501 * 60 + 20,
    )

    result = await runtime.startup()

    assert result.backfill_plan.limit == 500
    assert len(kline_store.added[0][1]) == 500
    assert len(recorder.executions) == 1
    assert recorder.notifications == [result.strategy_result]
    assert runtime.diagnostics["startup_backfill_inserted"] == 500


@pytest.mark.anyio
async def test_realtime_runtime_routes_open_candle_to_dashboard_without_execution_or_db_write():
    kline_store = FakeKlineStore(latest=_kline(BASE), latest_window=[_kline(BASE)])
    recorder = Recorder()
    runtime = RealtimeLiveStrategyRuntime(
        _task_config(),
        Config(window=500),
        db_manager=FakeDb(kline_store),
        exchange=FakeExchange([]),
        strategy_runner=recorder.run_strategy,
        notification_handler=recorder.notify,
        event_publisher=recorder.publish,
    )

    result = await runtime.handle_kline_update(_payload(BASE + 60, closed=False))

    assert result.strategy_result is None
    assert kline_store.added == []
    assert recorder.executions == []
    assert recorder.notifications == []
    assert [event.event_type for event in recorder.events] == ["kline_update"]


@pytest.mark.anyio
async def test_realtime_runtime_persists_closed_candle_executes_strategy_and_notifies():
    kline_store = FakeKlineStore(latest=_kline(BASE), latest_window=[_kline(BASE)])
    recorder = Recorder()
    exchange = FakeExchange([])
    runtime = RealtimeLiveStrategyRuntime(
        _task_config(),
        Config(window=500),
        db_manager=FakeDb(kline_store),
        exchange=exchange,
        strategy_runner=recorder.run_strategy,
        notification_handler=recorder.notify,
        event_publisher=recorder.publish,
    )

    result = await runtime.handle_kline_update(_payload(BASE + 60, closed=True))

    assert result.strategy_result is not None
    assert len(kline_store.added) == 1
    assert len(recorder.executions) == 1
    assert recorder.notifications == [result.strategy_result]
    assert exchange.new_order_calls == []
    assert [event.event_type for event in recorder.events] == ["kline_update", "strategy_execution", "signal_marker", "notification"]


@pytest.mark.anyio
async def test_realtime_runtime_dashboard_events_only_include_current_operations_after_history_merge():
    kline_store = FakeKlineStore(latest=_kline(BASE), latest_window=[_kline(BASE)])
    historical = Operate(OperateType.SELL, BASE - 60, 99.0)
    recorder = HistoryMergingRecorder(historical)
    runtime = RealtimeLiveStrategyRuntime(
        _task_config(),
        Config(window=500),
        db_manager=FakeDb(kline_store),
        exchange=FakeExchange([]),
        strategy_runner=recorder.run_strategy,
        notification_handler=recorder.notify,
        event_publisher=recorder.publish,
    )

    await runtime.handle_kline_update(_payload(BASE + 60, closed=True))

    markers = [event for event in recorder.events if event.event_type == "signal_marker"]
    assert len(markers) == 1
    assert markers[0].payload["time"] == BASE + 60


@pytest.mark.anyio
async def test_realtime_runtime_only_emits_new_operations_when_strategy_replays_window_history():
    kline_store = FakeKlineStore(latest=_kline(BASE), latest_window=[_kline(BASE)])
    recorder = WindowReplayRecorder()
    runtime = RealtimeLiveStrategyRuntime(
        _task_config(),
        Config(window=500),
        db_manager=FakeDb(kline_store),
        exchange=FakeExchange([]),
        strategy_runner=recorder.run_strategy,
        notification_handler=recorder.notify,
        event_publisher=recorder.publish,
    )

    await runtime.handle_kline_update(_payload(BASE + 60, closed=True))
    await runtime.handle_kline_update(_payload(BASE + 120, closed=True))

    markers = [event for event in recorder.events if event.event_type == "signal_marker"]
    assert [marker.payload["time"] for marker in markers] == [BASE, BASE + 60, BASE + 120]
    assert [len(result.opts) for result in recorder.notifications] == [2, 1]


@pytest.mark.anyio
async def test_realtime_runtime_does_not_emit_operations_already_saved_for_task():
    kline_store = FakeKlineStore(latest=_kline(BASE), latest_window=[_kline(BASE)])
    previous_result = StrategyResult([Operate(OperateType.BUY, BASE, 100.0)])
    recorder = WindowReplayRecorder()
    runtime = RealtimeLiveStrategyRuntime(
        _task_config(),
        Config(window=500),
        db_manager=FakeDb(kline_store, previous_result=previous_result),
        exchange=FakeExchange([]),
        strategy_runner=recorder.run_strategy,
        notification_handler=recorder.notify,
        event_publisher=recorder.publish,
    )

    await runtime.handle_kline_update(_payload(BASE + 60, closed=True))

    markers = [event for event in recorder.events if event.event_type == "signal_marker"]
    assert [marker.payload["time"] for marker in markers] == [BASE + 60]
    assert [op.dtime for op in recorder.notifications[0].opts] == [BASE + 60]


@pytest.mark.anyio
async def test_realtime_runtime_dedupes_closed_candle_execution():
    kline_store = FakeKlineStore(latest=_kline(BASE), latest_window=[_kline(BASE)])
    recorder = Recorder()
    runtime = RealtimeLiveStrategyRuntime(
        _task_config(),
        Config(window=500),
        db_manager=FakeDb(kline_store),
        exchange=FakeExchange([]),
        strategy_runner=recorder.run_strategy,
        notification_handler=recorder.notify,
        event_publisher=recorder.publish,
    )

    await runtime.handle_kline_update(_payload(BASE + 60, closed=True))
    duplicate = await runtime.handle_kline_update(_payload(BASE + 60, closed=True))

    assert duplicate.accepted is False
    assert len(recorder.executions) == 1
    assert len(kline_store.added) == 1
