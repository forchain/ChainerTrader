from types import SimpleNamespace

import pytest

from trader.common.config import Config
from trader.common.logger import Logger
from trader.live.dashboard import DashboardEvent
from trader.live.monitor import (
    LiveEventBus,
    build_initial_snapshot,
    build_live_strategy_summary,
    serialize_dashboard_event,
)
from trader.notify.notify_manager import NotifyManager
from trader.rpc.api.live import dispatch_debug_manual_signal, is_local_request
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.task.trader_task import TraderTask
from trader.utils.kline import Kline
from trader.utils.operate import Operate, OperateType
from trader.utils.symbol_interval import Interval, SymbolInterval
from trader.utils.task_state import TaskStateType

BASE = 1_714_281_600


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeTask:
    def __init__(self, task_id=7, state=TaskStateType.RUNNING, operations=None):
        self.tcfg = TaskConfig(
            id=task_id,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval.INTERVAL_1m),
            strategies=["macd_triple_divergence"],
            free=1000,
            strategy_params={"chainer_need_confirm": True, "chainer_risk_reward_ratio": 0},
            param_id="demo-fast",
            live_execution_mode="manual_notify",
        )
        self.ts = type("State", (), {"state": state, "tret": type("Result", (), {"opts": operations or []})()})()

    def id(self):
        return self.tcfg.id


class FakeKlineStore:
    def __init__(self, klines):
        self.klines = klines

    def get_latest_klines(self, name, limit):
        return self.klines[-limit:]


class FakeDb:
    def __init__(self, klines):
        self.kline = FakeKlineStore(klines)


class RecordingBus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


class RecordingNotice:
    tp = SimpleNamespace(name="MAIL_TEST")

    def __init__(self):
        self.sent = []

    def send(self, content, title="Trader"):
        self.sent.append((title, content))
        return None


def _kline(open_time, close=100):
    return Kline(open_time, close - 1, close + 1, close - 2, close, open_time + 59, 10, 1000, 10, 5, 500)


def test_build_live_strategy_summary_contains_web_panel_fields():
    summary = build_live_strategy_summary(FakeTask())

    assert summary["strategy_id"] == 7
    assert summary["symbol"] == "BTCUSDT"
    assert summary["interval"] == "1m"
    assert summary["strategy_name"] == "macd_triple_divergence"
    assert summary["execution_mode"] == "manual_notify"
    assert summary["status"] == "RUNNING"
    assert summary["task_id"] == 7
    assert summary["param_id"] == "demo-fast"
    assert summary["parameter_fingerprint"]
    assert "chainer_need_confirm=True" in summary["parameter_summary"]


def test_build_initial_snapshot_returns_latest_500_chart_candles():
    klines = [_kline(BASE + i * 60, close=100 + i) for i in range(600)]

    snapshot = build_initial_snapshot(FakeTask(), FakeDb(klines), runtime_status={"state": "running"})

    assert snapshot["strategy_id"] == 7
    assert snapshot["market"] == "BTCUSDT"
    assert snapshot["interval"] == "1m"
    assert len(snapshot["candles"]) == 500
    assert snapshot["candles"][0]["time"] == BASE + 100 * 60
    assert snapshot["runtime_status"]["state"] == "running"
    assert snapshot["task_id"] == 7
    assert snapshot["param_id"] == "demo-fast"
    assert snapshot["parameter_fingerprint"]
    assert snapshot["strategy_params"]["chainer_need_confirm"] is True
    assert snapshot["history_window"]["limit"] == 500
    assert snapshot["history_window"]["insufficient"] is False
    assert "signals" in snapshot["enabled_overlays"]


def test_build_initial_snapshot_returns_historical_operation_overlays_inside_loaded_window():
    visible_op = Operate(OperateType.BUY, BASE + 3 * 60, 103.0)
    visible_op.stop_loss = 99.0
    visible_op.take_profit = 111.0
    visible_op.signal_metadata = {"signal_event_id": "sig-1", "signal_type": "bottom_divergence"}
    hidden_op = Operate(OperateType.SELL, BASE - 60, 98.0)
    klines = [_kline(BASE + i * 60, close=100 + i) for i in range(5)]

    snapshot = build_initial_snapshot(FakeTask(operations=[hidden_op, visible_op]), FakeDb(klines), limit=5)

    assert [item["time"] for item in snapshot["overlays"]["signals"]] == [BASE + 3 * 60]
    assert snapshot["overlays"]["signals"][0]["signal_event_id"] == "sig-1"
    assert [item["overlay_type"] for item in snapshot["overlays"]["risk"]] == ["stop_loss", "take_profit"]
    assert snapshot["overlays"]["strategy_events"][0]["event_type"] == "macd_divergence"


def test_build_initial_snapshot_marks_history_window_insufficient():
    snapshot = build_initial_snapshot(FakeTask(), FakeDb([_kline(BASE)]))

    assert len(snapshot["candles"]) == 1
    assert snapshot["history_window"]["insufficient"] is True


def test_build_initial_snapshot_uses_task_state_when_runtime_status_is_not_provided():
    snapshot = build_initial_snapshot(FakeTask(state=TaskStateType.RUNNING), FakeDb([_kline(BASE)]))

    assert snapshot["runtime_status"]["state"] == "RUNNING"


def test_serialize_dashboard_event_returns_stable_json_shape():
    event = DashboardEvent("runtime_status", strategy_id=7, event_time=BASE, payload={"state": "running"})

    serialized = serialize_dashboard_event(event)

    assert serialized == {
        "event_type": "runtime_status",
        "strategy_id": 7,
        "event_time": BASE,
        "event_time_text": "2024-04-28 13:20:00",
        "payload": {"state": "running"},
    }


@pytest.mark.anyio
async def test_live_event_bus_filters_updates_by_strategy_id():
    bus = LiveEventBus()
    sub_7 = await bus.subscribe(7)
    sub_8 = await bus.subscribe(8)

    await bus.publish(DashboardEvent("kline_update", strategy_id=7, event_time=BASE, payload={"closed": False}))
    await bus.publish(DashboardEvent("kline_update", strategy_id=8, event_time=BASE, payload={"closed": True}))

    assert (await sub_7.get()).strategy_id == 7
    assert (await sub_8.get()).strategy_id == 8
    await sub_7.unsubscribe()
    await sub_8.unsubscribe()


@pytest.mark.anyio
async def test_debug_manual_entry_is_local_only_and_uses_standard_manual_notification_flow():
    cfg = Config(cash=10000.0)
    task = TraderTask(FakeTask().tcfg, cfg, Logger(cfg), db_manager=None, exchange=None)
    saved = []
    db = SimpleNamespace(
        kline=FakeKlineStore([_kline(BASE, close=100.0)]),
        task=SimpleNamespace(
            get_task=lambda task_id: None,
            add_tasks=lambda tasks: saved.extend(tasks),
        ),
    )
    task.db_manager = db
    notice = RecordingNotice()
    notify_mgr = NotifyManager(cfg, Logger(cfg))
    notify_mgr.notice = [notice]
    bus = RecordingBus()
    request = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        app=SimpleNamespace(
            state=SimpleNamespace(
                live_event_bus=bus,
                app=SimpleNamespace(
                    db_manager=db,
                    notify_mgr=notify_mgr,
                    task_manager=SimpleNamespace(get_task=lambda strategy_id: task),
                ),
            )
        ),
    )

    payload = await dispatch_debug_manual_signal(request, strategy_id=7, side="entry")

    assert is_local_request(request) is True
    assert payload["ok"] is True
    assert payload["notifications"][0]["action"] == "ENTRY"
    assert payload["notifications"][0]["stop_loss"] == 98.0
    assert len(notice.sent) == 1
    assert saved == [task.ts]
    assert [event.event_type for event in bus.events] == [
        "strategy_execution",
        "signal_marker",
        "risk_overlay",
        "notification",
    ]
