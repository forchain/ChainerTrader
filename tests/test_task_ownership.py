import asyncio
from datetime import datetime

from tortoise import Tortoise

from trader.app.app import App
from trader.common.config import Config
from trader.common.logger import Logger
from trader.database.config import build_tortoise_config
from trader.database.task import TaskCol
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig, parse_task_config
from trader.task.task_manager import TaskManager
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import Interval, SymbolInterval
from trader.utils.task_state import TaskState


class _Log:
    def debug(self, *_args, **_kwargs):
        pass

    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


async def _with_db(fn):
    await Tortoise.init(config=build_tortoise_config("sqlite://:memory:"))
    await Tortoise.generate_schemas()
    try:
        await fn()
    finally:
        await Tortoise.close_connections()


def test_parse_task_config_accepts_user_id():
    tasks = parse_task_config('[{"task_type":"DEBUG","limit":1,"user_id":42}]')

    assert tasks[0].user_id == 42


def test_send_add_tasks_msg_attaches_current_user_id():
    app = App(Config(tasks="[]"))
    app.queue = asyncio.Queue()

    result = app.send_add_tasks_msg('[{"task_type":"DEBUG","limit":1}]', user_id=42)

    assert result["tasks"][0]["user_id"] == 42


def test_task_repository_filters_by_user():
    async def run():
        store = TaskCol(_Log())
        first = TaskState(1, "first", datetime(2026, 1, 1), user_id=10)
        second = TaskState(2, "second", datetime(2026, 1, 1), user_id=20)
        await store.add_tasks([first, second])

        assert [task.id for task in await store.get_all_tasks_for_user(10)] == [1]
        assert await store.get_task_for_user(2, 10) is None

    asyncio.run(_with_db(run))


def test_task_manager_filters_running_tasks_by_user():
    cfg = Config(tasks="[]")
    manager = TaskManager(cfg, Logger(cfg), None, None)
    first_cfg = TaskConfig(1, TaskType.DEBUG, SymbolInterval("BTC-USDT", Interval("1h")), user_id=10)
    second_cfg = TaskConfig(2, TaskType.DEBUG, SymbolInterval("ETH-USDT", Interval("1h")), user_id=20)
    first = BaseTask(first_cfg, cfg, Logger(cfg))
    second = BaseTask(second_cfg, cfg, Logger(cfg))
    manager.tasks = {1: first, 2: second}

    async def run():
        assert [task.id for task in await manager.get_all_task_state(user_id=10)] == [1]
        assert await manager.get_task_state(2, user_id=10) is None

    asyncio.run(run())
