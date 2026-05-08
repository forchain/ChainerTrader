import asyncio
import threading
from types import SimpleNamespace

import pytest
from tortoise.context import TortoiseContext, get_current_context

from trader.common.config import Config
from trader.common.logger import Logger
from trader.execution.models import ExecutionSide, ExecutionStatus, GatewayMode, OrderIntent
from trader.execution.state import ExecutionStateRecord
from trader.live.auto_execution import AUTO_EXECUTION_EVENT_TYPE
from trader.live.market_data import BackfillPlan, BackfillRequestKind, normalize_binance_kline_message
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.task.trader_task import TraderTask
from trader.utils.kline import Kline
from trader.utils.operate import OperateType
from trader.utils.symbol_interval import Interval, SymbolInterval

BASE = 1_714_281_600


@pytest.fixture
def anyio_backend():
    return "asyncio"


class NoopStrategy:
    pass


class FakeKlineStore:
    def __init__(self):
        self.latest = None
        self.added = []
        self.by_open_time = {}

    def get_latest_kline(self, name):
        return self.latest

    def add_klines(self, name, klines):
        rows = list(klines)
        for row in rows:
            self.by_open_time[int(row.open_time)] = row
        self.added = [self.by_open_time[key] for key in sorted(self.by_open_time)]
        if self.added:
            self.latest = self.added[-1]
        return len(rows)

    def get_latest_klines(self, name, limit):
        return self.added[-limit:]


class FakeDb:
    def __init__(self):
        self.kline = FakeKlineStore()
        self.task = SimpleNamespace(get_task=lambda task_id: None, add_tasks=lambda tasks: None)


class FakeExchange:
    def __init__(self, fetched):
        self.fetched = fetched
        self.latest_requests = []
        self.new_order_calls = []
        self.balance_reads = []

    def name(self):
        return "BINANCE"

    def get_latest_klines(self, si, limit):
        self.latest_requests.append(limit)
        return self.fetched[-limit:]

    def get_klines(self, si, start_time=None, end_time=None, limit=500):
        return [kline for kline in self.fetched if start_time <= kline.open_time <= end_time][:limit]

    def get_account_balance(self, asset):
        self.balance_reads.append(asset)
        return 0.0

    def new_order(self, *args, **kwargs):
        self.new_order_calls.append((args, kwargs))
        raise AssertionError("manual_notify realtime runtime must not place exchange orders")


class FakeRunner:
    instances = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.started_warmup = None
        self.put_klines = []
        self.stopped = False
        FakeRunner.instances.append(self)

    def start(self, warmup=None):
        self.started_warmup = list(warmup or [])

    def put_kline(self, kline):
        self.put_klines.append(kline)
        return True

    def stop(self):
        self.stopped = True


class FakeSubscription:
    def __init__(self, updates, quit_event):
        self.updates = list(updates)
        self.quit_event = quit_event
        self.unsubscribed = False

    async def get(self):
        if self.updates:
            update = self.updates.pop(0)
            if not self.updates:
                self.quit_event.set()
            return update
        await asyncio.sleep(0.01)
        raise asyncio.TimeoutError

    async def unsubscribe(self):
        self.unsubscribed = True


class FakeHub:
    def __init__(self, updates, quit_event):
        self.updates = updates
        self.quit_event = quit_event
        self.subscription = None
        self.reconnect_callback = None

    async def subscribe(self, key, reconnect_callback=None):
        self.reconnect_callback = reconnect_callback
        self.subscription = FakeSubscription(self.updates, self.quit_event)
        return self.subscription


def _kline(open_time, close=100.0):
    return Kline(open_time, close - 1, close + 1, close - 2, close, open_time + 59, 1, 1, 1, 1, 1)


@pytest.mark.anyio
async def test_trader_task_persists_live_auto_execution_state_records():
    class StateStore:
        def __init__(self):
            self.saved = []

        async def save(self, record):
            self.saved.append(record)
            return record

    db = FakeDb()
    db.execution_state = StateStore()
    tcfg = TaskConfig(
        86,
        TaskType.TRADER,
        SymbolInterval("BTC-USDT", Interval.INTERVAL_1m),
        strategies=["macd_triple_divergence"],
        free=1000,
        live_execution_mode="small_live_auto",
        live_data_mode="realtime",
    )
    task = TraderTask(tcfg, Config(window=500), Logger(Config(window=500)), db, FakeExchange([]))
    intent = OrderIntent.entry(
        intent_id="intent-1",
        operation_id="op-1",
        symbol="BTCUSDT",
        side=ExecutionSide.LONG,
        quantity=0.25,
    )
    record = ExecutionStateRecord.from_order_intent(
        intent,
        gateway=GatewayMode.BINANCE_LIVE,
        staged_execution_mode="small_live_auto",
        status=ExecutionStatus.SUBMITTED,
        exchange_order_id="live-1",
        timestamp=BASE,
    )

    await task._persist_auto_execution_state(SimpleNamespace(execution_state_records=[record]))

    assert db.execution_state.saved == [record]


def _update(open_time, closed):
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
async def test_trader_task_realtime_uses_backtrader_live_runner_for_warmup_and_closed_updates(monkeypatch):
    FakeRunner.instances = []
    fetched = [_kline(BASE + i * 60, close=100 + i) for i in range(3)]
    cfg = Config(window=500)
    tcfg = TaskConfig(
        77,
        TaskType.TRADER,
        SymbolInterval("BTC-USDT", Interval.INTERVAL_1m),
        strategies=["macd_triple_divergence"],
        free=1000,
        live_execution_mode="manual_notify",
        live_data_mode="realtime",
    )
    task = TraderTask(tcfg, cfg, Logger(cfg), FakeDb(), FakeExchange(fetched))
    hub = FakeHub([_update(BASE + 180, closed=False), _update(BASE + 180, closed=True)], task.quit)

    monkeypatch.setattr("trader.task.trader_task.BacktraderLiveRunner", FakeRunner)
    monkeypatch.setattr("trader.task.trader_task.GLOBAL_MARKET_STREAM_HUB", hub)

    await task.start_realtime(asyncio.Queue(), [NoopStrategy])

    runner = FakeRunner.instances[0]
    assert "live_operation_sink" not in runner.kwargs["strategy_kwargs"]
    assert runner.kwargs["inject_operation_sink"] is True
    assert [kline.open_time for kline in runner.started_warmup] == [BASE, BASE + 60, BASE + 120]
    assert [kline.open_time for kline in runner.put_klines] == [BASE + 180]
    assert runner.stopped is True
    assert hub.subscription.unsubscribed is True


@pytest.mark.anyio
async def test_trader_task_realtime_fetches_latest_500_when_local_warmup_window_is_short(monkeypatch):
    FakeRunner.instances = []
    fetched = [_kline(BASE + i * 60, close=100 + i) for i in range(500)]
    db = FakeDb()
    db.kline.add_klines("BTCUSDT-1m", fetched[-2:])
    exchange = FakeExchange(fetched)
    cfg = Config(window=1000)
    tcfg = TaskConfig(
        81,
        TaskType.TRADER,
        SymbolInterval("BTC-USDT", Interval.INTERVAL_1m),
        strategies=["macd_triple_divergence"],
        free=1000,
        live_execution_mode="manual_notify",
        live_data_mode="realtime",
    )
    task = TraderTask(tcfg, cfg, Logger(cfg), db, exchange)

    class QuitOnSubscribeHub(FakeHub):
        async def subscribe(self, key, reconnect_callback=None):
            subscription = await super().subscribe(key, reconnect_callback=reconnect_callback)
            self.quit_event.set()
            return subscription

    hub = QuitOnSubscribeHub([], task.quit)
    monkeypatch.setattr("trader.task.trader_task.BacktraderLiveRunner", FakeRunner)
    monkeypatch.setattr("trader.task.trader_task.GLOBAL_MARKET_STREAM_HUB", hub)
    monkeypatch.setattr(
        "trader.task.trader_task.plan_initial_backfill",
        lambda *args, **kwargs: BackfillPlan(kind=BackfillRequestKind.NONE, limit=0, missing_count=0),
    )

    await task.start_realtime(asyncio.Queue(), [NoopStrategy])

    runner = FakeRunner.instances[0]
    assert 500 in exchange.latest_requests
    assert len(runner.started_warmup) == 500
    assert runner.started_warmup[0].open_time == BASE
    assert runner.started_warmup[-1].open_time == BASE + 499 * 60


@pytest.mark.anyio
async def test_trader_task_realtime_catches_up_missing_closed_klines_through_same_runner(monkeypatch):
    FakeRunner.instances = []
    warmup = [_kline(BASE, close=100), _kline(BASE + 60, close=101)]
    catch_up = [_kline(BASE + 120, close=102), _kline(BASE + 180, close=103)]
    cfg = Config(window=500)
    tcfg = TaskConfig(
        78,
        TaskType.TRADER,
        SymbolInterval("BTC-USDT", Interval.INTERVAL_1m),
        strategies=["macd_triple_divergence"],
        free=1000,
        live_execution_mode="manual_notify",
        live_data_mode="realtime",
    )
    db = FakeDb()
    db.kline.add_klines(tcfg.symbol_interval.name(), warmup)
    task = TraderTask(tcfg, cfg, Logger(cfg), db, FakeExchange(warmup + catch_up))
    hub = FakeHub([], task.quit)

    async def subscribe_and_reconnect(key, reconnect_callback=None):
        hub.reconnect_callback = reconnect_callback
        subscription = FakeSubscription([], task.quit)
        hub.subscription = subscription
        await reconnect_callback()
        task.quit.set()
        return subscription

    hub.subscribe = subscribe_and_reconnect
    plans = [
        BackfillPlan(kind=BackfillRequestKind.NONE, limit=0, missing_count=0),
        BackfillPlan(kind=BackfillRequestKind.RANGE, limit=2, missing_count=2, start_time=BASE + 120, end_time=BASE + 180),
    ]

    def next_plan(*args, **kwargs):
        return plans.pop(0)

    monkeypatch.setattr("trader.task.trader_task.BacktraderLiveRunner", FakeRunner)
    monkeypatch.setattr("trader.task.trader_task.GLOBAL_MARKET_STREAM_HUB", hub)
    monkeypatch.setattr("trader.task.trader_task.plan_initial_backfill", next_plan)

    await task.start_realtime(asyncio.Queue(), [NoopStrategy])

    runner = FakeRunner.instances[0]
    assert [kline.open_time for kline in runner.started_warmup] == [BASE, BASE + 60, BASE + 120, BASE + 180]
    assert [kline.open_time for kline in runner.put_klines] == [BASE + 120, BASE + 180]


@pytest.mark.anyio
async def test_trader_task_realtime_publishes_dashboard_events_and_runtime_status(monkeypatch):
    from trader.live.dashboard import DashboardEvent

    class OperationRunner(FakeRunner):
        def start(self, warmup=None):
            super().start(warmup=warmup)
            self.operation_handler = self.kwargs["operation_handler"]

        def put_kline(self, kline):
            super().put_kline(kline)
            operation_handler = self.kwargs["operation_handler"]
            op = SimpleNamespace(
                otype=OperateType.BUY,
                dtime=kline.open_time,
                price=101.0,
                signal_event_id="sig-1",
                to_dict=lambda: {"operate": "BUY", "datetime": kline.open_time, "price": 101.0},
            )
            operation_handler(op)
            return True

        def status(self):
            return {
                "feed_phase": "live",
                "latest_delivered_open_time": BASE + 180,
                "warmup_complete": True,
                "legacy_fallback": False,
            }

    FakeRunner.instances = []
    events = []
    fetched = [_kline(BASE + i * 60, close=100 + i) for i in range(3)]
    cfg = Config(window=500)
    tcfg = TaskConfig(
        79,
        TaskType.TRADER,
        SymbolInterval("BTC-USDT", Interval.INTERVAL_1m),
        strategies=["macd_triple_divergence"],
        free=1000,
        live_execution_mode="manual_notify",
        live_data_mode="realtime",
    )
    task = TraderTask(tcfg, cfg, Logger(cfg), FakeDb(), FakeExchange(fetched))
    hub = FakeHub([_update(BASE + 180, closed=True)], task.quit)

    async def capture_event(event: DashboardEvent):
        events.append(event)

    monkeypatch.setattr("trader.task.trader_task.BacktraderLiveRunner", OperationRunner)
    monkeypatch.setattr("trader.task.trader_task.GLOBAL_MARKET_STREAM_HUB", hub)
    monkeypatch.setattr("trader.task.trader_task.GLOBAL_LIVE_EVENT_BUS", SimpleNamespace(publish=capture_event))

    await task.start_realtime(asyncio.Queue(), [NoopStrategy])

    event_types = [event.event_type for event in events]
    assert "runtime_status" in event_types
    assert "kline_update" in event_types
    assert "strategy_execution" in event_types
    assert "signal_marker" in event_types
    assert "notification" in event_types
    status = next(event for event in events if event.event_type == "runtime_status")
    assert status.payload["feed_phase"] == "live"
    assert status.payload["latest_delivered_open_time"] == BASE + 180


@pytest.mark.anyio
async def test_trader_task_realtime_paper_auto_is_rejected_before_runtime(monkeypatch):
    with pytest.raises(ValueError, match="paper_auto is no longer supported"):
        TaskConfig(
            84,
            TaskType.TRADER,
            SymbolInterval("BTC-USDT", Interval.INTERVAL_1m),
            strategies=["macd_triple_divergence"],
            free=1000,
            live_execution_mode="paper_auto",
            live_data_mode="realtime",
        )


@pytest.mark.anyio
async def test_trader_task_realtime_preserves_tortoise_context_for_threaded_operations(monkeypatch):
    class ThreadedOperationRunner(FakeRunner):
        def put_kline(self, kline):
            super().put_kline(kline)
            operation_handler = self.kwargs["operation_handler"]
            op = SimpleNamespace(
                otype=OperateType.BUY,
                dtime=kline.open_time,
                price=101.0,
                signal_event_id="threaded-sig-1",
                to_dict=lambda: {"operate": "BUY", "datetime": kline.open_time, "price": 101.0},
            )
            thread = threading.Thread(target=lambda: operation_handler(op))
            thread.start()
            thread.join()
            return True

    class ContextRecordingTaskStore:
        def __init__(self):
            self.seen_contexts = []

        async def get_task(self, task_id):
            self.seen_contexts.append(get_current_context())
            return None

        async def add_tasks(self, tasks):
            return len(tasks)

    FakeRunner.instances = []
    fetched = [_kline(BASE + i * 60, close=100 + i) for i in range(3)]
    cfg = Config(window=500)
    tcfg = TaskConfig(
        83,
        TaskType.TRADER,
        SymbolInterval("BTC-USDT", Interval.INTERVAL_1m),
        strategies=["macd_triple_divergence"],
        free=1000,
        live_execution_mode="manual_notify",
        live_data_mode="realtime",
    )
    db = FakeDb()
    db.task = ContextRecordingTaskStore()
    task = TraderTask(tcfg, cfg, Logger(cfg), db, FakeExchange(fetched))
    hub = FakeHub([_update(BASE + 180, closed=True)], task.quit)

    monkeypatch.setattr("trader.task.trader_task.BacktraderLiveRunner", ThreadedOperationRunner)
    monkeypatch.setattr("trader.task.trader_task.GLOBAL_MARKET_STREAM_HUB", hub)

    with TortoiseContext() as ctx:
        await task.start_realtime(asyncio.Queue(), [NoopStrategy])
        await asyncio.sleep(0.01)

    assert db.task.seen_contexts == [ctx]


@pytest.mark.anyio
async def test_trader_task_realtime_publishes_warmup_operations_for_dashboard_without_notifications(monkeypatch):
    from trader.live.dashboard import DashboardEvent

    class WarmupOperationRunner(FakeRunner):
        def start(self, warmup=None):
            super().start(warmup=warmup)
            operation_handler = self.kwargs["operation_handler"]
            first = self.started_warmup[0]
            op = SimpleNamespace(
                otype=OperateType.BUY,
                dtime=first.open_time,
                price=first.close,
                feed_phase="warmup",
                signal_event_id="warmup-sig-1",
                to_dict=lambda: {"type": "BUY", "datetime": first.open_time, "price": first.close},
            )
            operation_handler(op)

        def status(self):
            return {
                "feed_phase": "warmup",
                "latest_delivered_open_time": BASE,
                "warmup_complete": False,
                "legacy_fallback": False,
            }

    FakeRunner.instances = []
    events = []
    fetched = [_kline(BASE + i * 60, close=100 + i) for i in range(2)]
    cfg = Config(window=500)
    tcfg = TaskConfig(
        80,
        TaskType.TRADER,
        SymbolInterval("BTC-USDT", Interval.INTERVAL_1m),
        strategies=["macd_triple_divergence"],
        free=1000,
        live_execution_mode="manual_notify",
        live_data_mode="realtime",
    )
    task = TraderTask(tcfg, cfg, Logger(cfg), FakeDb(), FakeExchange(fetched))

    class QuitOnSubscribeHub(FakeHub):
        async def subscribe(self, key, reconnect_callback=None):
            subscription = await super().subscribe(key, reconnect_callback=reconnect_callback)
            self.quit_event.set()
            return subscription

    hub = QuitOnSubscribeHub([], task.quit)

    async def capture_event(event: DashboardEvent):
        events.append(event)

    queue = asyncio.Queue()
    monkeypatch.setattr("trader.task.trader_task.BacktraderLiveRunner", WarmupOperationRunner)
    monkeypatch.setattr("trader.task.trader_task.GLOBAL_MARKET_STREAM_HUB", hub)
    monkeypatch.setattr("trader.task.trader_task.GLOBAL_LIVE_EVENT_BUS", SimpleNamespace(publish=capture_event))

    await task.start_realtime(queue, [NoopStrategy])

    event_types = [event.event_type for event in events]
    assert "strategy_execution" in event_types
    assert "signal_marker" in event_types
    assert "notification" not in event_types
    stat_msg = await queue.get()
    assert stat_msg.data.manual_trade_notifications == []


@pytest.mark.anyio
async def test_trader_task_realtime_does_not_disconnect_on_business_message_idle(monkeypatch):
    class IdleSubscription:
        def __init__(self, quit_event):
            self.quit_event = quit_event
            self.calls = 0

        async def get(self):
            self.calls += 1
            if self.calls >= 3:
                self.quit_event.set()
            await asyncio.sleep(0.01)
            raise asyncio.TimeoutError

        async def unsubscribe(self):
            return None

    class IdleHub:
        def __init__(self, quit_event):
            self.quit_event = quit_event
            self.disconnects = []

        async def subscribe(self, key, reconnect_callback=None):
            self.key = key
            self.reconnect_callback = reconnect_callback
            return IdleSubscription(self.quit_event)

        def status(self, key):
            return SimpleNamespace(state=SimpleNamespace(value="running"), subscriber_count=1, last_error=None)

        async def handle_disconnect(self, key):
            self.disconnects.append(key)
            self.quit_event.set()

    FakeRunner.instances = []
    fetched = [_kline(BASE + i * 60, close=100 + i) for i in range(3)]
    cfg = Config(window=500)
    tcfg = TaskConfig(
        82,
        TaskType.TRADER,
        SymbolInterval("BTC-USDT", Interval.INTERVAL_1m),
        strategies=["macd_triple_divergence"],
        free=1000,
        live_execution_mode="manual_notify",
        live_data_mode="realtime",
    )
    task = TraderTask(tcfg, cfg, Logger(cfg), FakeDb(), FakeExchange(fetched))
    hub = IdleHub(task.quit)

    monkeypatch.setattr("trader.task.trader_task.BacktraderLiveRunner", FakeRunner)
    monkeypatch.setattr("trader.task.trader_task.GLOBAL_MARKET_STREAM_HUB", hub)

    await asyncio.wait_for(task.start_realtime(asyncio.Queue(), [NoopStrategy]), timeout=0.5)

    assert hub.disconnects == []
