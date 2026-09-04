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
