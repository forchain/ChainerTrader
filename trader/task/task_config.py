import os

from trader.strategy.strategy import parseStrategyType
from trader.task.task_type import TaskType, parse_task_type
import json

from trader.utils.symbol_interval import SymbolInterval, Interval


class TaskConfig:
    def __init__(self,ttype:TaskType,symbol_interval=SymbolInterval("BTCUSDT",Interval("1d"))):
        self.ttype=ttype
        self.csv = None
        self.start_time=0
        self.end_time=0
        self.strategy=None
        self.symbol_interval = symbol_interval

        self.id=0

    def to_dict(self):
        return {
            'id': self.id,
            'type':self.ttype,
            'symbol_interval': self.symbol_interval.name(),
            'csv':self.csv,
            'start_time':self.start_time,
            'end_time':self.end_time,
        }

# '[{"task_type": "CHECK_KLINES", "start_time": 0,"end_time":0,"symbol":"BTCUSDT","interval":"1d","csv":"ETHUSDT-1h-202301-202401.csv","strategy","ShihunRSI2"}]'
def parse_task_config(cfg)->[TaskConfig]:
    if os.path.isfile(cfg):
        try:
            with open(cfg, 'r', encoding='utf-8') as file:
                parsed_list = json.load(file)
        except json.JSONDecodeError:
            return []
        except FileNotFoundError:
            return []
    else:
        parsed_list = json.loads(cfg)

    ret=[]
    for tcd in parsed_list:
        tc=TaskConfig(parse_task_type(tcd['task_type']),SymbolInterval(tcd['symbol'],Interval(tcd['interval'])))
        if "start_time" in tcd:
            tc.start_time=tcd['start_time']
        if "end_time" in tcd:
            tc.start_time=tcd['end_time']
        if "csv" in tcd:
            tc.csv=tcd['csv']
        if "strategy" in tcd:
            tc.strategy=parseStrategyType(tcd['strategy'])

        ret.append(tc)
    return ret

def get_symbols(tcfgs:[TaskConfig]):
    ret=[]
    for tcfg in tcfgs:
        ret.append(tcfg.symbol_interval.symbol)
    return ret

def get_symbols_from_cfg(cfg):
    return get_symbols(parse_task_config(cfg))