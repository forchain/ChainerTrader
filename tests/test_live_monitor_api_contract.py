import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
    current_task_workspace,
    dispatch_debug_manual_signal,
    is_local_request,
    list_live_strategies,
    live_debug_manual_entry,
    live_debug_manual_exit,
    live_strategy_events,
    live_strategy_snapshot,
    rerun_task,
)
from trader.rpc.api.task import get_task_operations
from trader.rpc.api.live import (
    router as live_router,
)
from trader.rpc.app import app as rpc_app
from trader.strategy.trader_result import TraderResult
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

    def get_klines(self, name, start_time=0, end_time=0):
        return [
            kline
            for kline in self.klines
            if (not start_time or kline.open_time >= start_time) and (not end_time or kline.open_time <= end_time)
        ]


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


class RecordingQueue:
    def __init__(self):
        self.messages = []

    def put_nowait(self, message):
        self.messages.append(message)


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


@pytest.mark.anyio
async def test_task_operations_api_returns_paginated_operations_with_known_type_labels():
    operations = [
        Operate(OperateType.LONG, BASE, 100.0),
        Operate(OperateType.SHORT, BASE + 60, 101.0),
        Operate(OperateType.CLOSE, BASE + 120, 102.0),
        Operate(OperateType.RISK_UPDATE, BASE + 180, 99.0),
    ]
    manager = SimpleNamespace(get_task_state=AsyncMock(return_value=SimpleNamespace(tret=SimpleNamespace(opts=operations))))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(app=SimpleNamespace(task_manager=manager))))

    payload = await get_task_operations(7, request, page=2, per_page=2)

    assert payload["task_id"] == 7
    assert payload["total"] == 4
    assert payload["page"] == 2
    assert payload["per_page"] == 2
    assert payload["total_pages"] == 2
    assert [item["type"] for item in payload["operations"]] == ["CLOSE", "RISK_UPDATE"]
    assert [item["type_label"] for item in payload["operations"]] == ["平仓", "风控更新"]


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


def test_admin_live_route_returns_monitor_layout():
    import trader.rpc.rpc_app as rpc_app_module

    rpc_app_module.os.kill = lambda pid, sig: None

    async def _sleep(logger, seconds, desc):
        await asyncio.sleep(0)

    rpc_app_module.sleep = _sleep
    rpc_app.state.app = SimpleNamespace(
        task_manager=SimpleNamespace(
            tasks={7: FakeTask()},
            get_all_task_state=lambda user_id=None: [],
            get_task=lambda task_id: FakeTask() if task_id == 7 else None,
        ),
        db_manager=FakeDb([_kline(BASE)]),
        cfg=Config(live_warmup_candles=20),
    )
    rpc_app.state.cfg = Config(api="127.0.0.1:0", tasks="[]")

    with TestClient(rpc_app) as client:
        response = client.get("/admin/live")

    assert response.status_code == 200
    assert "任务监控" in response.text
    assert "live-chart" in response.text
    assert "runtime-status" in response.text
    assert "diagnostic-events" in response.text


def test_admin_dashboard_renders_task_monitor_navigation_without_klines_entry():
    import trader.rpc.rpc_app as rpc_app_module

    rpc_app_module.os.kill = lambda pid, sig: None

    async def _sleep(logger, seconds, desc):
        await asyncio.sleep(0)

    rpc_app_module.sleep = _sleep
    rpc_app.state.app = SimpleNamespace(
        task_manager=SimpleNamespace(
            tasks={7: FakeTask()},
            get_all_task_state=lambda user_id=None: [],
            get_task=lambda task_id: FakeTask() if task_id == 7 else None,
        ),
        db_manager=FakeDb([_kline(BASE)]),
        cfg=Config(live_warmup_candles=20),
    )
    rpc_app.state.cfg = Config(api="127.0.0.1:0", tasks="[]")

    with TestClient(rpc_app) as client:
        response = client.get("/admin")

    assert response.status_code == 200
    assert "任务监控" in response.text
    assert "K线" not in response.text


@pytest.mark.anyio
async def test_current_task_workspace_prefers_running_task_and_uses_live_renderer():
    task = FakeTask(task_id=7, state=TaskStateType.RUNNING)
    running_state = SimpleNamespace(
        id=7,
        state=TaskStateType.RUNNING,
        name="7.TRADER.BTCUSDT-1m",
        start_time="2026-05-23 10:00:00",
        config_json='[{"task_type":"TRADER"}]',
    )
    async def all_states(user_id=None):
        return [running_state]
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    cfg=Config(live_warmup_candles=20),
                    task_manager=SimpleNamespace(
                        get_all_task_state=all_states,
                        get_task=lambda task_id: task if task_id == 7 else None,
                    ),
                    db_manager=FakeDb([_kline(BASE)]),
                )
            )
        )
    )

    payload = await current_task_workspace(request=request)

    assert payload["selected_task_id"] == 7
    assert payload["display_context"] == "active_running_task"
    assert payload["renderer"] == "live"
    assert payload["snapshot"]["task_id"] == 7


@pytest.mark.anyio
async def test_current_task_workspace_falls_back_to_latest_done_and_historical_selection():
    done_1 = SimpleNamespace(
        id=4,
        state=TaskStateType.DONE,
        name="4.BACK_TRADER.BTCUSDT-1h",
        start_time="2026-05-21 10:00:00",
        config_json='[{"task_type":"BACK_TRADER"}]',
    )
    done_2 = SimpleNamespace(
        id=9,
        state=TaskStateType.DONE,
        name="9.UPDATE_KLINES.BTCUSDT-1m",
        start_time="2026-05-22 10:00:00",
        config_json='[{"task_type":"UPDATE_KLINES"}]',
    )
    async def all_states(user_id=None):
        return [done_1, done_2]
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    task_manager=SimpleNamespace(
                        get_all_task_state=all_states,
                        get_task=lambda task_id: None,
                    ),
                    db_manager=FakeDb([]),
                )
            )
        )
    )

    fallback = await current_task_workspace(request=request)
    selected = await current_task_workspace(request=request, task_id=4)

    assert fallback["selected_task_id"] == 9
    assert fallback["display_context"] == "latest_finished_task"
    assert fallback["renderer"] == "data"
    assert selected["selected_task_id"] == 4
    assert selected["display_context"] == "historical_selection"
    assert selected["renderer"] == "backtest"


@pytest.mark.anyio
async def test_current_task_workspace_done_fallback_prefers_latest_finish_time():
    done_early_start_late_finish = SimpleNamespace(
        id=4,
        state=TaskStateType.DONE,
        name="4.BACK_TRADER.BTCUSDT-1h",
        start_time="2026-05-21 10:00:00",
        strategy_end_time="2026-05-23 09:00:00",
        config_json='[{"task_type":"BACK_TRADER"}]',
    )
    done_late_start_early_finish = SimpleNamespace(
        id=9,
        state=TaskStateType.DONE,
        name="9.UPDATE_KLINES.BTCUSDT-1m",
        start_time="2026-05-22 10:00:00",
        strategy_end_time="2026-05-22 11:00:00",
        config_json='[{"task_type":"UPDATE_KLINES"}]',
    )

    async def all_states(user_id=None):
        return [done_early_start_late_finish, done_late_start_early_finish]

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    task_manager=SimpleNamespace(
                        get_all_task_state=all_states,
                        get_task=lambda task_id: None,
                    ),
                    db_manager=FakeDb([]),
                )
            )
        )
    )

    payload = await current_task_workspace(request=request)

    assert payload["selected_task_id"] == 4
    assert payload["display_context"] == "latest_finished_task"
    assert payload["renderer"] == "backtest"


@pytest.mark.anyio
async def test_current_task_workspace_latest_done_backtest_run_returns_batch_chart_snapshot():
    btc_config = (
        '[{"task_type":"BACK_TRADER","symbol":"BTC-USDT","interval":"1m",'
        '"strategy":"macd_triple_divergence","run_id":"run-backtest"}]'
    )
    eth_config = (
        '[{"task_type":"BACK_TRADER","symbol":"ETH-USDT","interval":"1m",'
        '"strategy":"macd_triple_divergence","run_id":"run-backtest"}]'
    )
    backtest_btc = SimpleNamespace(
        id=30,
        state=TaskStateType.DONE,
        name="30.BACK_TRADER.BTCUSDT-1m",
        start_time="2026-05-23 10:00:00",
        strategy_start_time=BASE,
        strategy_end_time=BASE + 4 * 60,
        config_json=btc_config,
        tret=TraderResult(0.12, 0.02, timedelta(seconds=60), 0.1, 0.5, 1.2, 2.0, -1.0, 1, 0, [Operate(OperateType.BUY, BASE + 2 * 60, 102.0)], 0.3, 5),
    )
    backtest_eth = SimpleNamespace(
        id=31,
        state=TaskStateType.DONE,
        name="31.BACK_TRADER.ETHUSDT-1m",
        start_time="2026-05-23 10:00:01",
        strategy_start_time=BASE,
        strategy_end_time=BASE + 4 * 60,
        config_json=eth_config,
        tret=TraderResult(0.08, 0.01, timedelta(seconds=30), 0.1, 0.4, 1.1, 1.0, -1.0, 1, 0, [], 0.2, 5),
    )

    async def all_states(user_id=None):
        return [backtest_btc, backtest_eth]

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    cfg=Config(live_warmup_candles=20),
                    task_manager=SimpleNamespace(
                        get_all_task_state=all_states,
                        get_task=lambda task_id: None,
                    ),
                    db_manager=FakeDb([_kline(BASE + i * 60, close=100 + i) for i in range(5)]),
                )
            )
        )
    )

    payload = await current_task_workspace(request=request)

    assert payload["selected_task_id"] == 31
    assert payload["display_context"] == "latest_finished_task"
    assert payload["renderer"] == "backtest"
    assert [item["task_id"] for item in payload["tasks"]] == [31, 30]
    assert {item["run_id"] for item in payload["tasks"]} == {"run-backtest"}
    assert payload["snapshot"]["market"] == "ETHUSDT"
    assert payload["snapshot"]["interval"] == "1m"
    assert len(payload["snapshot"]["candles"]) == 5
    assert payload["snapshot"]["history_window"]["loaded"] == 5
    assert payload["snapshot"]["runtime_status"]["state"] == "DONE"

    selected_btc = await current_task_workspace(request=request, task_id=30)

    assert selected_btc["selected_task_id"] == 30
    assert [item["task_id"] for item in selected_btc["tasks"]] == [31, 30]
    assert selected_btc["snapshot"]["market"] == "BTCUSDT"
    assert selected_btc["snapshot"]["overlays"]["signals"][0]["price"] == 102.0
    assert selected_btc["snapshot"]["result_summary"]["total_return_rate"] == 0.12


@pytest.mark.anyio
async def test_current_task_workspace_lists_only_latest_running_batch_members():
    old_debug = SimpleNamespace(
        id=1,
        state=TaskStateType.DONE,
        name="1.DEBUG",
        start_time="2026-05-23 09:00:00",
        strategy_end_time="2026-05-23 09:01:00",
        config_json='[{"task_type":"DEBUG","run_id":"run-debug"}]',
    )
    live_btc = SimpleNamespace(
        id=10,
        state=TaskStateType.RUNNING,
        name="10.TRADER.BTCUSDT-1m",
        start_time="2026-05-23 10:00:00",
        config_json='[{"task_type":"TRADER","run_id":"run-live"}]',
    )
    live_eth = SimpleNamespace(
        id=11,
        state=TaskStateType.RUNNING,
        name="11.TRADER.ETHUSDT-1m",
        start_time="2026-05-23 10:00:01",
        config_json='[{"task_type":"TRADER","run_id":"run-live"}]',
    )

    async def all_states(user_id=None):
        return [old_debug, live_btc, live_eth]

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    cfg=Config(live_warmup_candles=20),
                    task_manager=SimpleNamespace(
                        get_all_task_state=all_states,
                        get_task=lambda task_id: FakeTask(task_id=task_id, state=TaskStateType.RUNNING),
                    ),
                    db_manager=FakeDb([_kline(BASE)]),
                )
            )
        )
    )

    payload = await current_task_workspace(request=request)

    assert payload["selected_task_id"] == 11
    assert [item["task_id"] for item in payload["tasks"]] == [11, 10]
    assert {item["run_id"] for item in payload["tasks"]} == {"run-live"}


@pytest.mark.anyio
async def test_current_task_workspace_sanitizes_recovery_only_config_json_metadata():
    recovered = SimpleNamespace(
        id=12,
        state=TaskStateType.DONE,
        name="12.TRADER.BTCUSDT-1m",
        start_time="2026-05-23 10:00:00",
        strategy_end_time=0,
        config_json=(
            '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m",'
            '"live_execution_mode":"auto_trade","persisted_legacy_live_execution_mode":"small_live_auto",'
            '"persisted_live_data_mode":"realtime","run_id":"run-live"}]'
        ),
    )

    async def all_states(user_id=None):
        return [recovered]

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    task_manager=SimpleNamespace(
                        get_all_task_state=all_states,
                        get_task=lambda task_id: None,
                    ),
                    db_manager=FakeDb([]),
                )
            )
        )
    )

    payload = await current_task_workspace(request=request)

    assert "persisted_legacy_live_execution_mode" not in payload["snapshot"]["config_json"]
    assert "persisted_live_data_mode" not in payload["snapshot"]["config_json"]


@pytest.mark.anyio
async def test_current_task_workspace_treats_legacy_latest_done_without_batch_as_single_task():
    latest_legacy = SimpleNamespace(
        id=20,
        state=TaskStateType.DONE,
        name="20.DEBUG",
        start_time="2026-05-23 11:00:00",
        strategy_end_time="2026-05-23 11:01:00",
        config_json='[{"task_type":"DEBUG"}]',
    )
    previous_batch_member = SimpleNamespace(
        id=19,
        state=TaskStateType.DONE,
        name="19.TRADER.BTCUSDT-1m",
        start_time="2026-05-23 10:00:00",
        strategy_end_time="2026-05-23 10:01:00",
        config_json='[{"task_type":"TRADER","run_id":"run-live"}]',
    )

    async def all_states(user_id=None):
        return [previous_batch_member, latest_legacy]

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    task_manager=SimpleNamespace(
                        get_all_task_state=all_states,
                        get_task=lambda task_id: None,
                    ),
                    db_manager=FakeDb([]),
                )
            )
        )
    )

    payload = await current_task_workspace(request=request)

    assert payload["selected_task_id"] == 20
    assert [item["task_id"] for item in payload["tasks"]] == [20]


@pytest.mark.anyio
async def test_current_task_workspace_returns_explicit_empty_payload_when_no_tasks():
    async def all_states(user_id=None):
        return []

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    task_manager=SimpleNamespace(
                        get_all_task_state=all_states,
                        get_task=lambda task_id: None,
                    ),
                    db_manager=FakeDb([]),
                )
            )
        )
    )

    payload = await current_task_workspace(request=request)

    assert payload["selected_task_id"] is None
    assert payload["display_context"] == "empty"
    assert payload["running_task_id"] is None
    assert payload["tasks"] == []
    assert payload["renderer"] == "generic"
    assert payload["snapshot"] is None


@pytest.mark.anyio
async def test_rerun_task_creates_new_task_from_saved_debug_config():
    saved = SimpleNamespace(
        id=42,
        state=TaskStateType.DONE,
        name="42.DEBUG",
        start_time="2026-05-23 10:00:00",
        config_json='[{"task_type":"DEBUG","limit":1}]',
    )
    queue = RecordingQueue()

    async def all_states(user_id=None):
        return [saved]

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    task_manager=SimpleNamespace(get_all_task_state=all_states),
                    queue=queue,
                ),
                cfg=Config(),
            )
        )
    )

    payload = await rerun_task(request=request, task_id=42)

    assert payload["result"] == "success"
    assert len(payload["tasks"]) == 1
    assert payload["tasks"][0]["id"] != 42
    assert payload["tasks"][0]["type"] == TaskType.DEBUG
    assert len(queue.messages) == 1
    assert queue.messages[0].is_add_tasks()
    taskcs = queue.messages[0].get_data()
    assert len(taskcs) == 1
    assert taskcs[0].id != 42
    assert taskcs[0].limit == 1


@pytest.mark.anyio
async def test_rerun_task_normalizes_legacy_compact_symbol_and_assigns_new_run():
    saved = SimpleNamespace(
        id=42,
        state=TaskStateType.DONE,
        name="42.TRADER.BTCUSDT-1m",
        start_time="2026-05-23 10:00:00",
        config_json=(
            '[{"task_type":"TRADER","symbol":"BTCUSDT","interval":"1m",'
            '"start_time":"2026-05-23 10:00:00","end_time":"2099-01-01 00:00:00",'
            '"strategy":"macd_triple_divergence","free":100,'
            '"live_execution_mode":"manual_notify",'
            '"live_trade_max_notional":20,"run_id":"run-old"}]'
        ),
    )
    queue = RecordingQueue()

    async def all_states(user_id=None):
        return [saved]

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    task_manager=SimpleNamespace(get_all_task_state=all_states),
                    queue=queue,
                ),
                cfg=Config(),
            )
        )
    )

    payload = await rerun_task(request=request, task_id=42)

    assert payload["result"] == "success"
    assert len(queue.messages) == 1
    taskcs = queue.messages[0].get_data()
    assert len(taskcs) == 1
    rerun_config = taskcs[0]
    assert rerun_config.id != 42
    assert rerun_config.symbol_interval.name() == "BTCUSDT-1m"
    assert rerun_config.strategies == ["macd_triple_divergence"]
    assert rerun_config.run_id
    assert rerun_config.run_id != "run-old"
    assert payload["tasks"][0]["id"] == rerun_config.id
    assert payload["tasks"][0]["run_id"] == rerun_config.run_id


@pytest.mark.anyio
async def test_rerun_task_assigns_new_run_for_already_parseable_saved_config():
    saved = SimpleNamespace(
        id=42,
        state=TaskStateType.DONE,
        name="42.TRADER.BTCUSDT-1m",
        start_time="2026-05-23 10:00:00",
        config_json=(
            '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m",'
            '"strategy":"macd_triple_divergence","free":100,'
            '"live_trade_max_notional":20,"run_id":"run-old"}]'
        ),
    )
    queue = RecordingQueue()

    async def all_states(user_id=None):
        return [saved]

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    task_manager=SimpleNamespace(get_all_task_state=all_states),
                    queue=queue,
                ),
                cfg=Config(),
            )
        )
    )

    await rerun_task(request=request, task_id=42)

    taskcs = queue.messages[0].get_data()
    assert len(taskcs) == 1
    assert taskcs[0].id != 42
    assert taskcs[0].run_id
    assert taskcs[0].run_id != "run-old"


@pytest.mark.anyio
async def test_rerun_task_public_response_does_not_expose_recovery_only_metadata(monkeypatch):
    saved = SimpleNamespace(
        id=42,
        state=TaskStateType.DONE,
        name="42.TRADER.BTCUSDT-1m",
        start_time="2026-05-23 10:00:00",
        config_json=(
            '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m",'
            '"strategy":"macd_triple_divergence","live_execution_mode":"auto_trade",'
            '"persisted_legacy_live_execution_mode":"small_live_auto",'
            '"persisted_live_data_mode":"realtime","run_id":"run-old"}]'
        ),
    )
    queue = RecordingQueue()

    async def all_states(user_id=None):
        return [saved]

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    task_manager=SimpleNamespace(get_all_task_state=all_states),
                    queue=queue,
                ),
                cfg=Config(),
            )
        )
    )

    payload = await rerun_task(request=request, task_id=42)

    assert payload["result"] == "success"
    assert "persisted_legacy_live_execution_mode" not in payload["tasks"][0]
    assert "persisted_live_data_mode" not in payload["tasks"][0]


@pytest.mark.anyio
async def test_rerun_task_rehydrates_recovery_only_metadata_internally():
    saved = SimpleNamespace(
        id=43,
        state=TaskStateType.DONE,
        name="43.TRADER.BTCUSDT-1m",
        start_time="2026-05-23 10:00:00",
        config_json=(
            '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m",'
            '"strategy":"macd_triple_divergence","live_execution_mode":"auto_trade",'
            '"persisted_legacy_live_execution_mode":"small_live_auto",'
            '"persisted_live_data_mode":"realtime","run_id":"run-old"}]'
        ),
    )
    queue = RecordingQueue()

    async def all_states(user_id=None):
        return [saved]

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                app=SimpleNamespace(
                    task_manager=SimpleNamespace(get_all_task_state=all_states),
                    queue=queue,
                ),
                cfg=Config(),
            )
        )
    )

    payload = await rerun_task(request=request, task_id=43)

    taskcs = queue.messages[0].get_data()
    assert payload["result"] == "success"
    assert getattr(taskcs[0], "persisted_legacy_live_execution_mode", None) == "small_live_auto"
    assert getattr(taskcs[0], "persisted_live_data_mode", None) is None
    assert not hasattr(taskcs[0], "live_data_mode")


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
