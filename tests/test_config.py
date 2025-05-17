import os

from trader.common.config import Config
from trader.common.path import GetScriptsDir
from trader.task.task_config import TaskConfig, get_symbols, parse_task_config
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import SymbolInterval, Interval


def test_config():
    cfg = Config()
    print(cfg.to_dict())

def test_symbols():
    cfgs = [TaskConfig(TaskType.TRADER,SymbolInterval("BTCUSDT",Interval.INTERVAL_1d)),
            TaskConfig(TaskType.TRADER,SymbolInterval("ETHUSDT",Interval.INTERVAL_1d))]
    print(get_symbols(cfgs))

def test_symbols_intervals():
    cfgs = [TaskConfig(TaskType.TRADER, SymbolInterval("BTCUSDT", Interval.INTERVAL_1d)),
            TaskConfig(TaskType.TRADER, SymbolInterval("ETHUSDT", Interval.INTERVAL_1d))]
    for si in cfgs:
        print(si.symbol_interval.name())

def test_taskconfig():
    file=os.path.join(GetScriptsDir(),"multi_backtrader.json")
    tcfgs=parse_task_config(file)
    for tcfg in tcfgs:
        print(tcfg.to_dict())