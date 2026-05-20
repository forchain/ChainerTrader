import asyncio
from contextlib import asynccontextmanager

import pytest

from trader.common.config import Config
from trader.rpc import app as rpc_module
from trader.rpc.rpc_app import RpcApp


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

        def start(self):
            events.append("app.start")

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

    assert events[:4] == ["db.bootstrap", "app.start", "handler.ready", "error.check"]
    assert events[-1] == "app.stop"
