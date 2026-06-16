import asyncio
from types import SimpleNamespace

from trader.app.app import App
from trader.common.config import Config
from trader.common.logger import Logger
from trader.common.message import new_add_tasks_msg
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig
from trader.task.task_manager import TaskManager
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import Interval, SymbolInterval
from trader.utils.task_state import TaskState, TaskStateType


def test_task_manager_start_returns_none_when_tasks_parse_to_empty():
    cfg = Config(
        tasks='[{"task_type":"BACK_TRADER","symbol":"ETHUSDT","interval":"1h","strategy":"macd_triple_divergence","csv":"data/ETHUSDT-1h-202301-202401.csv"}]'
    )
    task_manager = TaskManager(cfg, Logger(cfg), None, None)

    assert task_manager.start() is None


def test_app_start_returns_false_when_task_manager_returns_no_message(monkeypatch):
    cfg = Config(tasks='[{"task_type":"BACK_TRADER","symbol":"ETHUSDT","interval":"1h","strategy":"macd_triple_divergence"}]')
    app = App(cfg)

    monkeypatch.setattr(app.task_manager, "start", lambda: None)
    monkeypatch.setattr(app, "process", lambda msgs: (_ for _ in ()).throw(AssertionError("process should not be called")))

    assert app.start() is False


def test_app_start_runs_startup_self_check_before_task_launch(monkeypatch):
    cfg = Config(
        tasks='[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1h","strategy":"macd_triple_divergence","strategy_params":{"chainer_mode":"BOTH"}}]',
        exchange='{"ty":"BINANCE","driver":"ccxt","api_key":"k","api_secret":"s"}',
    )
    app = App(cfg)
    calls = []

    monkeypatch.setattr(app.exchange, "start", lambda: calls.append("exchange.start"))
    monkeypatch.setattr(app, "process", lambda msgs: calls.append(("process", len(msgs))))
    monkeypatch.setattr(app.task_manager, "start", lambda *args, **kwargs: calls.append(("task_manager.start", len(args))) or None)

    assert app.start() is False
    assert "exchange.start" in calls
    assert any(item[0] == "task_manager.start" for item in calls if isinstance(item, tuple))
    assert hasattr(app, "startup_self_check")
    assert app.startup_self_check.required_margin_mode.value == "cross_margin"


def test_app_promotes_exchange_margin_mode_for_short_capable_tasks():
    cfg = Config(
        tasks='[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1h","strategy":"macd_triple_divergence","strategy_params":{"chainer_mode":"BOTH"}}]',
        exchange='{"ty":"BINANCE","driver":"ccxt","api_key":"k","api_secret":"s"}',
    )
    app = App(cfg)

    assert app.exchange is not None
    assert app.exchange.margin_mode.value == "cross_margin"


def test_base_task_stop_without_db_manager_does_not_crash():
    cfg = Config(tasks="[]")
    tcfg = TaskConfig(
        id=1,
        ttype=TaskType.BACK_TRADER,
        symbol_interval=SymbolInterval("ETH-USDT", Interval("1h")),
        strategies=["macd_triple_divergence"],
    )
    task = BaseTask(tcfg, cfg, Logger(cfg))

    task.start(None)
    task.stop()

    assert task.ts.state.name == "DONE"


def test_base_task_start_persists_running_state_immediately():
    cfg = Config(tasks="[]")
    saved_batches = []

    async def add_tasks(states):
        saved_batches.append([state.to_dict() for state in states])
        return len(states)

    db_manager = SimpleNamespace(task=SimpleNamespace(add_tasks=add_tasks))
    tcfg = TaskConfig(
        id=3,
        ttype=TaskType.DEBUG,
        symbol_interval=SymbolInterval("ETH-USDT", Interval("1h")),
        strategies=[],
    )
    task = BaseTask(tcfg, cfg, Logger(cfg), db_manager)

    task.start(None)

    assert saved_batches
    assert saved_batches[0][0]["task_id"] == tcfg.id
    assert saved_batches[0][0]["state"] == "RUNNING"


def test_app_start_restores_running_tasks_from_database(monkeypatch):
    cfg = Config(tasks="[]", api="0.0.0.0:8000")
    app = App(cfg)
    recovered = TaskConfig(
        id=11,
        ttype=TaskType.DEBUG,
        symbol_interval=SymbolInterval("BTC-USDT", Interval("1h")),
        strategies=[],
    )
    running_state = SimpleNamespace(
        id=recovered.id,
        state=SimpleNamespace(name="RUNNING"),
        config_json='[{"task_type":"DEBUG","limit":1,"user_id":7,"run_id":"run-11"}]',
        user_id=7,
        to_dict=lambda: {
            "task_id": recovered.id,
            "state": "RUNNING",
            "config_json": '[{"task_type":"DEBUG","limit":1,"user_id":7,"run_id":"run-11"}]',
        },
    )
    events = []

    class _FakeTaskRepo:
        async def get_all_tasks(self):
            events.append("db.get_all_tasks")
            return [running_state]

    class _FakeDbManager:
        started = True
        task = _FakeTaskRepo()

        async def start(self):
            events.append("db.start")

        async def get_startup_admin(self):
            return SimpleNamespace(id=1)

    recovered_calls = []

    def _fake_process(msgs):
        app.queue = asyncio.Queue()
        app._mark_handler_ready()
        asyncio.run(app._recover_running_tasks_in_background())
        events.append(("process", len(msgs)))

    app.db_manager = _FakeDbManager()

    async def _recover_task(taskc, queue):
        recovered_calls.append((taskc.id, taskc.user_id, taskc.run_id))

    app.task_manager = SimpleNamespace(
        start=lambda *_args, **_kwargs: None,
        recover_task=_recover_task,
    )
    app.process = _fake_process

    monkeypatch.setattr("trader.app.app.parse_task_config", lambda _cfg: [recovered])

    assert app.start() is True
    assert "db.get_all_tasks" in events
    assert recovered_calls == [(recovered.id, 7, "run-11")]


def test_app_start_skips_startup_task_when_matching_running_task_will_recover(monkeypatch):
    cfg = Config(tasks='[{"task_type":"DEBUG","limit":1}]', api="0.0.0.0:8000")
    app = App(cfg)
    running_state = SimpleNamespace(
        id=42,
        state=SimpleNamespace(name="RUNNING"),
        config_json='[{"task_type":"DEBUG","limit":1,"user_id":1,"run_id":"run-42"}]',
        user_id=1,
    )
    events = []

    class _FakeTaskRepo:
        async def get_all_tasks(self):
            events.append("db.get_all_tasks")
            return [running_state]

    class _FakeDbManager:
        started = True
        task = _FakeTaskRepo()

        async def start(self):
            events.append("db.start")

        async def get_startup_admin(self):
            return SimpleNamespace(id=1)

    def _fake_process(msgs):
        app.queue = asyncio.Queue()
        app._mark_handler_ready()
        asyncio.run(app._recover_running_tasks_in_background())
        events.append(("process", len(msgs)))

    recovered_calls = []

    async def _recover_task(taskc, queue):
        recovered_calls.append((taskc.id, taskc.user_id, taskc.run_id))

    app.db_manager = _FakeDbManager()
    app.task_manager = SimpleNamespace(
        start=lambda taskcs: new_add_tasks_msg(taskcs) if taskcs else None,
        recover_task=_recover_task,
    )
    app.process = _fake_process

    assert app.start() is True
    assert ("process", 0) in events
    assert recovered_calls == [(42, 1, "run-42")]


def test_task_manager_awaits_completed_task_state_persistence():
    async def _test():
        cfg = Config(tasks="[]")
        saved_batches = []

        async def add_tasks(states):
            await asyncio.sleep(0)
            saved_batches.append([state.to_dict() for state in states])
            return len(states)

        db_manager = SimpleNamespace(task=SimpleNamespace(add_tasks=add_tasks))
        task_manager = TaskManager(cfg, Logger(cfg), db_manager, None)
        task_config = TaskConfig(
            id=2,
            ttype=TaskType.DEBUG,
            symbol_interval=SymbolInterval("ETH-USDT", Interval("1h")),
            strategies=[],
        )

        async def fake_add_task(taskc, queue):
            task = BaseTask(taskc, cfg, Logger(cfg), db_manager)
            task_manager.tasks[task.id()] = task
            await task.start(queue)

        task_manager.add_task = fake_add_task

        await task_manager.do_add_tasks([task_config], asyncio.Queue())

        assert [batch[0]["state"] for batch in saved_batches] == ["RUNNING", "DONE"]
        assert all(batch[0]["task_id"] == task_config.id for batch in saved_batches)

    asyncio.run(_test())


def test_task_manager_recover_task_keeps_running_state_persisted():
    cfg = Config(tasks="[]")
    logger = Logger(cfg)

    async def _test():
        saved_batches = []
        release_task = asyncio.Event()

        async def add_tasks(states):
            saved_batches.append([state.to_dict() for state in states])
            return len(states)

        class _FakeLongRunningTask(BaseTask):
            async def start(self, queue):
                await super().start(queue)
                await release_task.wait()

        db_manager = SimpleNamespace(task=SimpleNamespace(add_tasks=add_tasks))
        task_manager = TaskManager(cfg, logger, db_manager, None)
        task_config = TaskConfig(
            id=5,
            ttype=TaskType.DEBUG,
            symbol_interval=SymbolInterval("ETH-USDT", Interval("1h")),
            strategies=[],
        )

        task_manager._build_task = lambda task_cfg, exchange: _FakeLongRunningTask(task_cfg, cfg, logger, db_manager)

        await task_manager.recover_task(task_config, asyncio.Queue())
        await asyncio.sleep(0)

        assert task_config.id in task_manager.tasks
        assert task_manager.tasks[task_config.id].ts.state.name == "RUNNING"
        assert [batch[0]["state"] for batch in saved_batches] == ["RUNNING"]

        release_task.set()
        await asyncio.gather(*task_manager.async_tasks)

    asyncio.run(_test())


def test_task_manager_close_preserves_running_live_tasks_for_restart_recovery():
    cfg = Config(tasks="[]")
    logger = Logger(cfg)

    async def _test():
        saved_batches = []

        async def add_tasks(states):
            saved_batches.append([state.to_dict() for state in states])
            return len(states)

        db_manager = SimpleNamespace(task=SimpleNamespace(add_tasks=add_tasks))
        task_manager = TaskManager(cfg, logger, db_manager, None)
        task_config = TaskConfig(
            id=9,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1h")),
            strategies=["macd_triple_divergence"],
            live_data_mode="realtime",
        )
        task = BaseTask(task_config, cfg, logger, db_manager)
        await task.start(asyncio.Queue())
        task_manager.tasks[task.id()] = task
        saved_batches.clear()

        await task_manager.close()

        assert task.ts.state == TaskStateType.RUNNING
        assert saved_batches[-1][0]["state"] == "RUNNING"

    asyncio.run(_test())


def test_task_manager_dispatch_shutdown_preserves_running_live_tasks_for_restart_recovery():
    cfg = Config(tasks="[]")
    logger = Logger(cfg)

    async def _test():
        saved_batches = []

        async def add_tasks(states):
            saved_batches.append([state.to_dict() for state in states])
            return len(states)

        class _FakeLiveTraderTask(BaseTask):
            async def start(self, queue):
                await super().start(queue)
                await self.quit.wait()

        db_manager = SimpleNamespace(task=SimpleNamespace(add_tasks=add_tasks))
        task_manager = TaskManager(cfg, logger, db_manager, None)
        task_config = TaskConfig(
            id=10,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1h")),
            strategies=["macd_triple_divergence"],
            live_data_mode="realtime",
        )
        task_manager._build_task = lambda task_cfg, exchange: _FakeLiveTraderTask(task_cfg, cfg, logger, db_manager, exchange)

        task_manager.add_tasks([task_config], asyncio.Queue())
        while task_config.id not in task_manager.tasks:
            await asyncio.sleep(0)

        await task_manager.close()

        assert task_config.id in task_manager.tasks
        assert task_manager.tasks[task_config.id].ts.state == TaskStateType.RUNNING
        assert [batch[0]["state"] for batch in saved_batches] == ["RUNNING", "RUNNING"]

    asyncio.run(_test())


def test_task_manager_closes_persisted_running_task_not_loaded_in_memory():
    cfg = Config(tasks="[]")
    logger = Logger(cfg)

    async def _test():
        persisted = TaskState(
            8,
            "8.DEBUG",
            __import__("datetime").datetime.now(),
            config_json='[{"task_type":"DEBUG","limit":1,"user_id":3,"run_id":"run-8"}]',
            user_id=3,
        )
        persisted.state = TaskStateType.RUNNING
        saved_batches = []

        class _TaskRepo:
            async def get_task_for_user(self, task_id, user_id):
                if task_id == persisted.id and user_id == persisted.user_id:
                    return persisted
                return None

            async def add_tasks(self, states):
                saved_batches.append([state.to_dict() for state in states])
                return len(states)

        task_manager = TaskManager(cfg, logger, SimpleNamespace(task=_TaskRepo()), None)

        assert await task_manager.close_task_state(8, user_id=3) is True
        assert persisted.state == TaskStateType.DONE
        assert saved_batches[-1][0]["state"] == "DONE"

    asyncio.run(_test())
