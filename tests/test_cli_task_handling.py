import asyncio
from types import SimpleNamespace

from trader.app.app import App
from trader.common.config import Config
from trader.common.logger import Logger
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig
from trader.task.task_manager import TaskManager
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import Interval, SymbolInterval


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


def test_task_manager_awaits_completed_task_state_persistence():
    async def _test():
        cfg = Config(tasks="[]")
        saved_batches = []

        async def add_tasks(states):
            await asyncio.sleep(0)
            saved_batches.append(list(states))
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
            task.start(queue)

        task_manager.add_task = fake_add_task

        await task_manager.do_add_tasks([task_config], asyncio.Queue())

        assert len(saved_batches) == 1
        assert saved_batches[0][0].id == task_config.id
        assert saved_batches[0][0].state.name == "DONE"

    asyncio.run(_test())
