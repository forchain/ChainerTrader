import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trader.live.dashboard import DashboardEvent
from trader.live.monitor import (
    LiveEventBus,
    build_initial_snapshot,
    build_live_strategy_summary,
    serialize_dashboard_event,
)
from trader.common.config import Config
from trader.rpc.api.live import (
    _normalize_rerun_config_json,
    dispatch_debug_manual_signal,
    is_local_request,
    list_live_strategies,
    list_monitor_tasks,
    live_debug_manual_entry,
    live_debug_manual_exit,
    live_monitor_task_rerun,
    live_strategy_events,
    live_strategy_snapshot,
)
from trader.rpc.api.live import (
    router as live_router,
)
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
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


class FakeLiveTask:
    def __init__(self, tcfg):
        self.tcfg = tcfg
        self.ts = SimpleNamespace(tret=None)
        self._saved_results = []

    async def process_result(self, result):
        self.ts.tret = result
        self._saved_results.append(result)

    def handle_manual_trade_notifications(self, result):
        op = (result.opts or [None])[0]
        action = "EXIT" if getattr(op, "otype", None) == OperateType.CLOSE else "ENTRY"
        event = SimpleNamespace(
            to_dict=lambda: {
                "action": action,
                "symbol": self.tcfg.symbol_interval.symbol(),
                "stop_loss": float(getattr(op, "stop_loss", 0.0) or 0.0),
            }
        )
        return [event]


class FakeNotifyManager:
    def send_manual_trade_notification(self, event):
        return [{"ok": True, "provider": "fake"}]


class _Logger:
    def __init__(self):
        self.infos = []
        self.errors = []

    def info(self, message):
        self.infos.append(message)

    def error(self, message):
        self.errors.append(message)


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

    snapshot = asyncio.run(build_initial_snapshot(FakeTask(), FakeDb(klines), runtime_status={"state": "running"}))

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


@pytest.mark.anyio
async def test_live_strategy_snapshot_api_uses_configured_live_warmup_candles_limit():
    klines = [_kline(BASE + i * 60, close=100 + i) for i in range(120)]
    task = FakeTask()
    manager = SimpleNamespace(tasks={7: task}, get_task=lambda strategy_id: task if strategy_id == 7 else None)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(task_manager=manager, db_manager=FakeDb(klines), cfg=Config(live_warmup_candles=50))
            )
        )
    )

    payload = await live_strategy_snapshot(7, request)

    assert len(payload["candles"]) == 50
    assert payload["history_window"]["limit"] == 50


def test_build_initial_snapshot_returns_historical_operation_overlays_inside_loaded_window():
    visible_op = Operate(OperateType.BUY, BASE + 3 * 60, 103.0)
    visible_op.stop_loss = 99.0
    visible_op.take_profit = 111.0
    visible_op.signal_metadata = {"signal_event_id": "sig-1", "signal_type": "bottom_divergence"}
    hidden_op = Operate(OperateType.SELL, BASE - 60, 98.0)
    klines = [_kline(BASE + i * 60, close=100 + i) for i in range(5)]

    snapshot = asyncio.run(build_initial_snapshot(FakeTask(operations=[hidden_op, visible_op]), FakeDb(klines), limit=5))

    assert [item["time"] for item in snapshot["overlays"]["signals"]] == [BASE + 3 * 60]
    assert snapshot["overlays"]["signals"][0]["signal_event_id"] == "sig-1"
    assert [item["overlay_type"] for item in snapshot["overlays"]["risk"]] == ["stop_loss", "take_profit"]
    assert snapshot["overlays"]["strategy_events"][0]["event_type"] == "macd_divergence"


def test_build_initial_snapshot_marks_history_window_insufficient():
    snapshot = asyncio.run(build_initial_snapshot(FakeTask(), FakeDb([_kline(BASE)])))

    assert len(snapshot["candles"]) == 1
    assert snapshot["history_window"]["insufficient"] is True


def test_build_initial_snapshot_uses_task_state_when_runtime_status_is_not_provided():
    snapshot = asyncio.run(build_initial_snapshot(FakeTask(state=TaskStateType.RUNNING), FakeDb([_kline(BASE)])))

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


def test_normalize_rerun_config_json_rewrites_user_id_and_symbol_format():
    raw = '[{"task_type":"BACK_TRADER","symbol":"ETHUSDT","interval":"1h","user_id":99}]'
    normalized = _normalize_rerun_config_json(raw, user_id=2)
    payload = __import__("json").loads(normalized)
    assert payload[0]["user_id"] == 2
    assert payload[0]["symbol"] == "ETH-USDT"


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
    task = FakeLiveTask(FakeTask().tcfg)
    db = SimpleNamespace(
        kline=FakeKlineStore([_kline(BASE, close=100.0)]),
        task=SimpleNamespace(get_task=lambda task_id: None, add_tasks=lambda tasks: len(tasks)),
    )
    bus = RecordingBus()
    request = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        app=SimpleNamespace(
            state=SimpleNamespace(
                live_event_bus=bus,
                app=SimpleNamespace(
                    db_manager=db,
                    notify_mgr=FakeNotifyManager(),
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
    assert [event.event_type for event in bus.events] == [
        "strategy_execution",
        "signal_marker",
        "risk_overlay",
        "notification",
    ]


def test_list_live_strategies_api_returns_sorted_strategy_summaries():
    task_a = FakeTask(task_id=2)
    task_b = FakeTask(task_id=1)
    manager = SimpleNamespace(tasks={2: task_a, 1: task_b})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(app=SimpleNamespace(task_manager=manager))))

    payload = asyncio.run(list_live_strategies(request))

    assert [item["strategy_id"] for item in payload] == [1, 2]
    assert payload[0]["execution_mode"] == "manual_notify"


@pytest.mark.anyio
async def test_list_monitor_tasks_returns_task_type_state_and_config_json():
    running_task = FakeTask(task_id=7, state=TaskStateType.RUNNING)
    done_state = SimpleNamespace(
        id=8,
        state=TaskStateType.DONE,
        name="8.DEBUG",
        config_json='[{"task_type":"DEBUG","user_id":5}]',
        user_id=5,
        to_dict=lambda: {
            "task_id": 8,
            "state": "DONE",
            "name": "8.DEBUG",
            "config_json": '[{"task_type":"DEBUG","user_id":5}]',
            "user_id": 5,
        },
    )

    async def get_all_task_state(user_id=None):
        return [running_task.ts, done_state]

    async def fake_current_user(_request):
        return SimpleNamespace(id=5, is_admin=False)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("trader.rpc.api.live.current_user", fake_current_user)
    logger = _Logger()
    manager = SimpleNamespace(tasks={7: running_task}, get_all_task_state=get_all_task_state)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(app=SimpleNamespace(task_manager=manager, logger=logger))))
    try:
        payload = await list_monitor_tasks(request)
        assert [item["task_id"] for item in payload] == [7, 8]
        assert payload[0]["task_type"] == "TRADER"
        assert payload[0]["monitor_mode"] == "live"
        assert payload[0]["state"] == "RUNNING"
        assert payload[1]["task_type"] == "DEBUG"
        assert payload[1]["monitor_mode"] == "historical"
        assert payload[1]["can_rerun"] is True
        assert "user_id=5" in logger.infos[0]
        assert "count=2" in logger.infos[0]
    finally:
        monkeypatch.undo()


@pytest.mark.anyio
async def test_live_monitor_task_rerun_reuses_finished_task_config_for_current_user():
    send_add_tasks_msg = lambda cfg, user_id=None: {"result": "success", "cfg": cfg, "user_id": user_id}
    done_state = SimpleNamespace(
        id=8,
        state=TaskStateType.DONE,
        config_json='[{"task_type":"DEBUG","symbol":"ETHUSDT","user_id":5}]',
    )

    async def fake_current_user(_request):
        return SimpleNamespace(id=5, is_admin=False)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("trader.rpc.api.live.current_user", fake_current_user)

    async def get_task_state(task_id, user_id=None):
        assert user_id == 5
        return done_state if task_id == 8 else None

    logger = _Logger()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    task_manager=SimpleNamespace(get_task_state=get_task_state),
                    send_add_tasks_msg=send_add_tasks_msg,
                    logger=logger,
                )
            )
        )
    )

    try:
        payload = await live_monitor_task_rerun(8, request=request)

        assert payload["result"] == "success"
        assert payload["user_id"] == 5
        cfg_payload = __import__("json").loads(payload["cfg"])
        assert cfg_payload[0]["task_type"] == "DEBUG"
        assert cfg_payload[0]["symbol"] == "ETH-USDT"
        assert cfg_payload[0]["user_id"] == 5
        assert "user_id=5" in logger.infos[0]
        assert "task_id=8" in logger.infos[0]
    finally:
        monkeypatch.undo()


@pytest.mark.anyio
async def test_live_monitor_task_rerun_returns_http_400_when_enqueue_rejected():
    done_state = SimpleNamespace(
        id=8,
        state=TaskStateType.DONE,
        config_json='[{"task_type":"DEBUG","user_id":5}]',
    )

    async def fake_current_user(_request):
        return SimpleNamespace(id=5, is_admin=False)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("trader.rpc.api.live.current_user", fake_current_user)

    async def get_task_state(task_id, user_id=None):
        assert task_id == 8
        assert user_id == 5
        return done_state

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    task_manager=SimpleNamespace(get_task_state=get_task_state),
                    send_add_tasks_msg=lambda *_args, **_kwargs: {"result": "fail", "error": "queue rejected"},
                    logger=_Logger(),
                )
            )
        )
    )

    try:
        with pytest.raises(Exception) as exc:
            await live_monitor_task_rerun(8, request=request)
        assert getattr(exc.value, "status_code", None) == 400
        assert "queue rejected" in str(getattr(exc.value, "detail", ""))
    finally:
        monkeypatch.undo()


@pytest.mark.anyio
async def test_live_monitor_task_rerun_failure_logs_user_id():
    logger = _Logger()

    async def fake_current_user(_request):
        return SimpleNamespace(id=5, is_admin=False)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("trader.rpc.api.live.current_user", fake_current_user)

    async def get_task_state(task_id, user_id=None):
        assert task_id == 9
        assert user_id == 5
        return None

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    task_manager=SimpleNamespace(get_task_state=get_task_state),
                    logger=logger,
                )
            )
        )
    )

    try:
        with pytest.raises(Exception) as exc:
            await live_monitor_task_rerun(9, request=request)
        assert getattr(exc.value, "status_code", None) == 404
        assert "user_id=5" in logger.errors[0]
        assert "task_id=9" in logger.errors[0]
    finally:
        monkeypatch.undo()


@pytest.mark.anyio
async def test_live_strategy_snapshot_api_returns_not_found_for_unknown_strategy():
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    task_manager=SimpleNamespace(get_task=lambda strategy_id: None),
                    db_manager=FakeDb([]),
                )
            )
        )
    )

    with pytest.raises(Exception) as exc:
        await live_strategy_snapshot(strategy_id=404, request=request)

    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.anyio
async def test_live_strategy_snapshot_api_returns_snapshot_payload():
    task = FakeTask(task_id=7)
    klines = [_kline(BASE + i * 60, close=100 + i) for i in range(3)]
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    task_manager=SimpleNamespace(get_task=lambda strategy_id: task),
                    db_manager=FakeDb(klines),
                )
            )
        )
    )

    payload = await live_strategy_snapshot(strategy_id=7, request=request)

    assert payload["strategy_id"] == 7
    assert len(payload["candles"]) == 3
    assert payload["candles"][-1]["close"] == 102.0


def test_live_api_http_smoke_lists_strategies_and_loads_snapshot():
    task = FakeTask(task_id=7)
    klines = [_kline(BASE + i * 60, close=100 + i) for i in range(3)]
    app = FastAPI()
    app.include_router(live_router, prefix="/api/live")
    app.state.app = SimpleNamespace(
        task_manager=SimpleNamespace(
            tasks={7: task},
            get_task=lambda strategy_id: task if strategy_id == 7 else None,
        ),
        db_manager=FakeDb(klines),
    )
    app.state.live_event_bus = LiveEventBus()

    client = TestClient(app)

    strategies = client.get("/api/live/strategies")
    snapshot = client.get("/api/live/strategies/7/snapshot")

    assert strategies.status_code == 200
    assert strategies.json()[0]["strategy_id"] == 7
    assert snapshot.status_code == 200
    assert snapshot.json()["candles"][-1]["close"] == 102.0


@pytest.mark.anyio
async def test_live_strategy_events_api_streams_serialized_events():
    bus = LiveEventBus()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(live_event_bus=bus)))
    response = await live_strategy_events(strategy_id=7, request=request)

    producer_done = asyncio.Event()

    async def producer():
        await bus.publish(DashboardEvent("runtime_status", strategy_id=7, event_time=BASE, payload={"state": "running"}))
        producer_done.set()

    asyncio.create_task(producer())
    body_iter = response.body_iterator
    chunk = await anext(body_iter)
    await producer_done.wait()
    await body_iter.aclose()

    text = chunk if isinstance(chunk, str) else chunk.decode("utf-8")
    assert response.media_type == "text/event-stream"
    assert '"event_type": "runtime_status"' in text
    assert '"strategy_id": 7' in text
    assert '"state": "running"' in text


@pytest.mark.anyio
async def test_live_debug_manual_entry_endpoint_delegates_to_dispatch(monkeypatch):
    captured = {}

    async def fake_dispatch(request, strategy_id, side):
        captured["strategy_id"] = strategy_id
        captured["side"] = side
        return {"ok": True, "side": side}

    monkeypatch.setattr("trader.rpc.api.live.dispatch_debug_manual_signal", fake_dispatch)
    payload = await live_debug_manual_entry(11, request=SimpleNamespace())

    assert payload == {"ok": True, "side": "entry"}
    assert captured == {"strategy_id": 11, "side": "entry"}


@pytest.mark.anyio
async def test_live_debug_manual_exit_endpoint_delegates_to_dispatch(monkeypatch):
    captured = {}

    async def fake_dispatch(request, strategy_id, side):
        captured["strategy_id"] = strategy_id
        captured["side"] = side
        return {"ok": True, "side": side}

    monkeypatch.setattr("trader.rpc.api.live.dispatch_debug_manual_signal", fake_dispatch)
    payload = await live_debug_manual_exit(12, request=SimpleNamespace())

    assert payload == {"ok": True, "side": "exit"}
    assert captured == {"strategy_id": 12, "side": "exit"}
