import asyncio
from contextlib import asynccontextmanager

import pytest

from trader.common.config import Config
from trader.rpc import app as rpc_module
from trader.rpc.rpc_app import RpcApp
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import Interval, SymbolInterval


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_rpc_app_logs_main_task_failure(monkeypatch):
    app = RpcApp(Config())
    error = RuntimeError("startup failed")

    async def fail_handler(msgs, quit):
        raise error

    monkeypatch.setattr(app, "handler", fail_handler)
    app.process([])

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert app.main_task.done()
    assert app.main_task_error is error
    with pytest.raises(RuntimeError, match="startup failed"):
        app.raise_main_task_error()
    with pytest.raises(RuntimeError, match="startup failed"):
        await app.wait_until_handler_ready()


@pytest.mark.anyio
async def test_rpc_app_processes_initial_task_message(monkeypatch):
    app = RpcApp(Config(tasks="[]"))
    seen = []

    async def fake_handler(msgs, quit):
        seen.extend(msgs)

    monkeypatch.setattr(app, "handler", fake_handler)
    monkeypatch.setattr("trader.rpc.rpc_app.sleep", lambda logger, seconds, desc: asyncio.sleep(0))
    monkeypatch.setattr("trader.rpc.rpc_app.os.kill", lambda pid, sig: None)

    message = object()
    app.process([message])
    await app.wait_until_handler_ready()
    await app.main_task

    assert seen == [message]


@pytest.mark.anyio
async def test_rpc_app_api_mode_ignores_startup_tasks_and_startup_admin(monkeypatch):
    app = RpcApp(
        Config(
            tasks='[{"task_type":"DEBUG","limit":1}]',
            api="0.0.0.0:8000",
        )
    )
    process_calls = []

    class FakeDbManager:
        started = True

        async def start(self):
            raise AssertionError("db.start should not be called")

        async def get_startup_admin(self):
            raise AssertionError("startup admin should not be requested in API mode")

    monkeypatch.setattr(app.notify_mgr, "start", lambda: None)
    monkeypatch.setattr(
        app.task_manager,
        "start",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("startup tasks should be ignored in API mode")),
    )
    monkeypatch.setattr(app, "process", lambda msgs: process_calls.append(list(msgs)))
    app.db_manager = FakeDbManager()

    result = await app.start_async()

    assert result is True
    assert process_calls == [[]]
    assert not hasattr(app, "startup_self_check")


@pytest.mark.anyio
async def test_rpc_app_waits_until_handler_ready(monkeypatch):
    app = RpcApp(Config(tasks="[]"))
    ready_reached = asyncio.Event()
    unblock = asyncio.Event()

    async def fake_handler(msgs, quit):
        app._mark_handler_ready()
        ready_reached.set()
        await unblock.wait()

    monkeypatch.setattr(app, "handler", fake_handler)
    monkeypatch.setattr("trader.rpc.rpc_app.sleep", lambda logger, seconds, desc: asyncio.sleep(0))
    monkeypatch.setattr("trader.rpc.rpc_app.os.kill", lambda pid, sig: None)

    app.process([])
    await app.wait_until_handler_ready()

    assert ready_reached.is_set()
    assert not app.main_task.done()

    unblock.set()
    await app.main_task


@pytest.mark.anyio
async def test_rpc_lifespan_bootstraps_database_before_exchange_start(monkeypatch):
    events = []

    class FakeRpcApp:
        def __init__(self, cfg):
            self.cfg = cfg

        async def bootstrap_database_for_startup(self):
            events.append("db.bootstrap")

        async def start_async(self):
            events.append("app.start_async")

        async def wait_until_handler_ready(self):
            events.append("handler.ready")

        def raise_main_task_error(self):
            events.append("error.check")

        async def stop(self):
            events.append("app.stop")

    monkeypatch.setattr(rpc_module, "RpcApp", FakeRpcApp)

    class State:
        cfg = Config(tasks="[]")

    @asynccontextmanager
    async def run_lifespan():
        async with rpc_module.lifespan(type("App", (), {"state": State()})()):
            events.append("yielded")
            yield

    async with run_lifespan():
        pass

    assert events[:4] == ["db.bootstrap", "app.start_async", "handler.ready", "error.check"]
    assert events[-1] == "app.stop"


@pytest.mark.anyio
async def test_rpc_app_async_start_schedules_recovery_without_waiting_for_scan(monkeypatch):
    app = RpcApp(Config(tasks="[]", api="0.0.0.0:8000"))
    recovered = TaskConfig(
        id=11,
        ttype=TaskType.DEBUG,
        symbol_interval=SymbolInterval("BTC-USDT", Interval("1h")),
        strategies=[],
    )
    running_state = type(
        "State",
        (),
        {
            "id": 11,
            "state": type("TaskState", (), {"name": "RUNNING"})(),
            "config_json": '[{"task_type":"DEBUG","limit":1,"user_id":7,"run_id":"run-11"}]',
            "user_id": 7,
        },
    )()
    process_seen = []
    scan_release = asyncio.Event()
    recovered_started = asyncio.Event()
    release_recover = asyncio.Event()

    class FakeTaskRepo:
        async def get_all_tasks(self):
            await scan_release.wait()
            return [running_state]

    class FakeDbManager:
        started = True
        task = FakeTaskRepo()

    monkeypatch.setattr(app.notify_mgr, "start", lambda: None)
    monkeypatch.setattr(
        app,
        "process",
        lambda msgs: (
            process_seen.extend(msgs),
            setattr(app, "queue", asyncio.Queue()),
            app._mark_handler_ready(),
            app._schedule_recovery_tasks(),
        ),
    )
    monkeypatch.setattr(app.task_manager, "start", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        app.task_manager,
        "recover_task",
        lambda taskc, queue: _recover_task(taskc, queue, recovered_started, release_recover),
    )
    monkeypatch.setattr("trader.app.app.parse_task_config", lambda _cfg: [recovered])
    app.db_manager = FakeDbManager()

    result = await app.start_async()

    assert result is True
    assert process_seen == []
    assert not recovered_started.is_set()

    scan_release.set()
    await asyncio.wait_for(recovered_started.wait(), timeout=1)
    assert app.recovery_task is not None

    release_recover.set()
    await asyncio.wait_for(app.recovery_task, timeout=1)


@pytest.mark.anyio
async def test_rpc_app_recovery_limits_concurrent_task_starts(monkeypatch):
    app = RpcApp(Config(tasks="[]", api="0.0.0.0:8000"))
    states = [
        type(
            "State",
            (),
            {
                "id": idx,
                "state": type("TaskState", (), {"name": "RUNNING"})(),
                "config_json": f'[{{"task_type":"DEBUG","limit":1,"run_id":"run-{idx}"}}]',
                "user_id": 7,
            },
        )()
        for idx in range(1, 6)
    ]
    active = 0
    max_active = 0
    started_ids = []
    release_recover = asyncio.Event()

    class FakeTaskRepo:
        async def get_all_tasks(self):
            return states

    class FakeDbManager:
        started = True
        task = FakeTaskRepo()

    async def fake_recover_task(taskc, queue):
        nonlocal active, max_active
        started_ids.append(taskc.id)
        active += 1
        max_active = max(max_active, active)
        await release_recover.wait()
        active -= 1

    monkeypatch.setattr(app.notify_mgr, "start", lambda: None)
    monkeypatch.setattr(
        app,
        "process",
        lambda msgs: (
            setattr(app, "queue", asyncio.Queue()),
            app._mark_handler_ready(),
            app._schedule_recovery_tasks(),
        ),
    )
    monkeypatch.setattr(app.task_manager, "start", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app.task_manager, "recover_task", fake_recover_task)
    monkeypatch.setattr("trader.app.app.parse_task_config", lambda cfg: [TaskConfig(id=1, ttype=TaskType.DEBUG, symbol_interval=SymbolInterval("BTC-USDT", Interval("1h")), strategies=[])])
    monkeypatch.setattr("trader.app.app.RECOVERY_TASK_CONCURRENCY", 2)
    app.db_manager = FakeDbManager()

    result = await app.start_async()

    assert result is True

    for _ in range(5):
        await asyncio.sleep(0)

    assert max_active == 2
    assert started_ids == [1, 2]

    release_recover.set()
    await asyncio.wait_for(app.recovery_task, timeout=1)


@pytest.mark.anyio
async def test_rpc_app_recovery_fails_loudly_for_legacy_persisted_live_config(monkeypatch):
    app = RpcApp(Config(tasks="[]", api="0.0.0.0:8000"))
    running_state = type(
        "State",
        (),
        {
            "id": 21,
            "state": type("TaskState", (), {"name": "RUNNING"})(),
            "config_json": (
                '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m","strategy":"macd_triple_divergence",'
                '"live_execution_mode":"small_live_auto","live_data_mode":"realtime","run_id":"run-21"}]'
            ),
            "user_id": 7,
        },
    )()
    class FakeTaskRepo:
        async def get_all_tasks(self):
            return [running_state]

    class FakeDbManager:
        started = True
        task = FakeTaskRepo()

    monkeypatch.setattr(app.notify_mgr, "start", lambda: None)
    monkeypatch.setattr(
        app,
        "process",
        lambda msgs: (
            setattr(app, "queue", asyncio.Queue()),
            app._mark_handler_ready(),
            app._schedule_recovery_tasks(),
        ),
    )
    monkeypatch.setattr(app.task_manager, "start", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "trader.app.app.parse_task_config",
        lambda _cfg: (_ for _ in ()).throw(AssertionError("legacy rows must be rejected before parse_task_config")),
    )
    app.db_manager = FakeDbManager()

    result = await app.start_async()

    assert result is True
    with pytest.raises(RuntimeError, match="persisted live task\\(21\\) recovery failed"):
        await asyncio.wait_for(app.recovery_task, timeout=1)


@pytest.mark.anyio
async def test_rpc_app_recovery_fails_loudly_for_unmigratable_manual_notify_polling(monkeypatch):
    app = RpcApp(Config(tasks="[]", api="0.0.0.0:8000"))
    running_state = type(
        "State",
        (),
        {
            "id": 23,
            "state": type("TaskState", (), {"name": "RUNNING"})(),
            "config_json": (
                '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m","strategy":"macd_triple_divergence",'
                '"live_execution_mode":"manual_notify","live_data_mode":"polling","run_id":"run-23"}]'
            ),
            "user_id": 7,
        },
    )()

    class FakeTaskRepo:
        async def get_all_tasks(self):
            return [running_state]

    class FakeDbManager:
        started = True
        task = FakeTaskRepo()

    monkeypatch.setattr(app.notify_mgr, "start", lambda: None)
    monkeypatch.setattr(
        app,
        "process",
        lambda msgs: (
            setattr(app, "queue", asyncio.Queue()),
            app._mark_handler_ready(),
            app._schedule_recovery_tasks(),
        ),
    )
    monkeypatch.setattr(app.task_manager, "start", lambda *_args, **_kwargs: None)
    app.db_manager = FakeDbManager()

    result = await app.start_async()

    assert result is True
    with pytest.raises(RuntimeError, match="persisted live task\\(23\\) recovery failed"):
        await asyncio.wait_for(app.recovery_task, timeout=1)


@pytest.mark.anyio
async def test_rpc_app_recovery_fails_loudly_for_malformed_running_config_json(monkeypatch):
    app = RpcApp(Config(tasks="[]", api="0.0.0.0:8000"))
    running_state = type(
        "State",
        (),
        {
            "id": 24,
            "state": type("TaskState", (), {"name": "RUNNING"})(),
            "config_json": '{"task_type":"TRADER"',
            "user_id": 7,
        },
    )()

    class FakeTaskRepo:
        async def get_all_tasks(self):
            return [running_state]

    class FakeDbManager:
        started = True
        task = FakeTaskRepo()

    monkeypatch.setattr(app.notify_mgr, "start", lambda: None)
    monkeypatch.setattr(
        app,
        "process",
        lambda msgs: (
            setattr(app, "queue", asyncio.Queue()),
            app._mark_handler_ready(),
            app._schedule_recovery_tasks(),
        ),
    )
    monkeypatch.setattr(app.task_manager, "start", lambda *_args, **_kwargs: None)
    app.db_manager = FakeDbManager()

    result = await app.start_async()

    assert result is True
    with pytest.raises(RuntimeError, match="persisted running task\\(24\\) recovery failed"):
        await asyncio.wait_for(app.recovery_task, timeout=1)


@pytest.mark.anyio
async def test_rpc_app_recovery_fails_loudly_for_missing_running_config_json(monkeypatch):
    app = RpcApp(Config(tasks="[]", api="0.0.0.0:8000"))
    running_state = type(
        "State",
        (),
        {
            "id": 25,
            "state": type("TaskState", (), {"name": "RUNNING"})(),
            "config_json": None,
            "user_id": 7,
        },
    )()

    class FakeTaskRepo:
        async def get_all_tasks(self):
            return [running_state]

    class FakeDbManager:
        started = True
        task = FakeTaskRepo()

    monkeypatch.setattr(app.notify_mgr, "start", lambda: None)
    monkeypatch.setattr(
        app,
        "process",
        lambda msgs: (
            setattr(app, "queue", asyncio.Queue()),
            app._mark_handler_ready(),
            app._schedule_recovery_tasks(),
        ),
    )
    monkeypatch.setattr(app.task_manager, "start", lambda *_args, **_kwargs: None)
    app.db_manager = FakeDbManager()

    result = await app.start_async()

    assert result is True
    with pytest.raises(RuntimeError, match="persisted running task\\(25\\) is missing config_json"):
        await asyncio.wait_for(app.recovery_task, timeout=1)


@pytest.mark.anyio
async def test_rpc_app_recovery_accepts_already_migrated_persisted_live_config(monkeypatch):
    app = RpcApp(Config(tasks="[]", api="0.0.0.0:8000"))
    running_state = type(
        "State",
        (),
        {
            "id": 22,
            "state": type("TaskState", (), {"name": "RUNNING"})(),
            "config_json": (
                '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m","strategy":"macd_triple_divergence",'
                '"live_execution_mode":"auto_trade","run_id":"run-22"}]'
            ),
            "user_id": 8,
        },
    )()
    recovered_calls = []

    class FakeTaskRepo:
        async def get_all_tasks(self):
            return [running_state]

    class FakeDbManager:
        started = True
        task = FakeTaskRepo()

    monkeypatch.setattr(app.notify_mgr, "start", lambda: None)
    monkeypatch.setattr(
        app,
        "process",
        lambda msgs: (
            setattr(app, "queue", asyncio.Queue()),
            app._mark_handler_ready(),
            app._schedule_recovery_tasks(),
        ),
    )
    monkeypatch.setattr(app.task_manager, "start", lambda *_args, **_kwargs: None)
    async def fake_recover_task(taskc, queue):
        recovered_calls.append((taskc.id, taskc.user_id, taskc.run_id))

    monkeypatch.setattr(
        app.task_manager,
        "recover_task",
        fake_recover_task,
    )
    app.db_manager = FakeDbManager()

    result = await app.start_async()

    assert result is True
    await asyncio.wait_for(app.recovery_task, timeout=1)
    assert recovered_calls == [(22, 8, "run-22")]


async def _recover_task(taskc, queue, started_event: asyncio.Event, release_event: asyncio.Event):
    started_event.set()
    await release_event.wait()
