from types import SimpleNamespace

import pytest

from trader.app.app import App
from trader.common.config import Config
from trader.common.message import new_add_tasks_msg, new_exit_msg
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import Interval, SymbolInterval


class _FakeDbManager:
    def __init__(self, admin):
        self._admin = admin
        self.started = False
        self.events = None

    async def start(self):
        self.started = True
        if self.events is not None:
            self.events.append("db.start")

    async def stop(self):
        self.started = False

    async def get_startup_admin(self):
        return self._admin


def _debug_task(task_id: int) -> TaskConfig:
    return TaskConfig(task_id, TaskType.DEBUG, SymbolInterval("BTC-USDT", Interval("1h")))


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_handler_attaches_startup_tasks_to_admin_user_id():
    app = App(Config(tasks="[]"))
    tasks = [_debug_task(1)]
    app.db_manager = _FakeDbManager(SimpleNamespace(id=42, username="admin", role="admin"))
    captured = []

    def _fake_add_tasks(taskcs, _queue):
        captured.extend(taskcs)

    app.task_manager.add_tasks = _fake_add_tasks
    await app.handler([new_add_tasks_msg(tasks), new_exit_msg()], SimpleNamespace(is_set=lambda: False, set=lambda: None))

    assert captured
    assert captured[0].user_id == 42


def test_start_bootstraps_database_before_exchange_start():
    app = App(Config(tasks="[]"))
    events = []
    app.db_manager = _FakeDbManager(SimpleNamespace(id=42, username="admin", role="admin"))
    app.db_manager.events = events
    app.exchange = SimpleNamespace(start=lambda: events.append("exchange.start"))
    app.notify_mgr = SimpleNamespace(start=lambda: events.append("notify.start"))
    app.task_manager = SimpleNamespace(start=lambda *_args, **_kwargs: None)
    app.process = lambda _msgs: events.append("process")

    app.start()

    assert events.index("db.start") < events.index("exchange.start")
