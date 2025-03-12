import os

from trader.common import path
from trader.common.common import parse_datetime
from trader.task.task_type import TaskType, parse_task_type
import json

from trader.utils.symbol_interval import SymbolInterval, Interval
from trader.utils.symbols_interval import SymbolsInterval

class TaskConfig:
    def __init__(self,ttype:TaskType,symbol_interval=SymbolInterval("BTCUSDT",Interval("1d")),csv=None,start_time=0,end_time=0,strategys:[str]=None,auto_download=False):
        self.ttype=ttype
        self.csv = csv
        self.start_time=start_time
        self.end_time=end_time
        self.strategys=strategys
        self.symbol_interval = symbol_interval
        self.auto_download = auto_download

        self.id=0

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.ttype,
            'symbol_interval': self.symbol_interval.name(),
            'csv': self.csv,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'strategys': self.strategys,
            'auto_download': self.auto_download,
        }

    def strategy_name(self):
        if self.strategys is None:
            return None
        s=""
        for st in self.strategys:
            if len(s) > 0:
                s+="+"+st
            else:
                s+=st
        return s


# '[{"task_type": "CHECK_KLINES", "start_time": "2023-09-24 14:30:00","end_time":"0","symbol":"BTCUSDT","interval":"1d","csv":"ETHUSDT-1h-202301-202401.csv","strategy","ShihunRSI2"}]'
def parse_task_config(cfg)->[TaskConfig]:
    file_path=path.get_file_path(cfg)
    if os.path.isfile(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                parsed_list = json.load(file)
        except json.JSONDecodeError:
            return []
        except FileNotFoundError:
            return []
    else:
        parsed_list = json.loads(cfg)

    ret=[]
    index = 0
    for tcd in parsed_list:
        task_type = parse_task_type(tcd['task_type'])

        if "symbols" in tcd:
            sis = SymbolsInterval(tcd['symbols'], Interval(tcd['interval']))
        else:
            sis = SymbolsInterval(tcd['symbol'], Interval(tcd['interval']))

        start_time = 0
        if "start_time" in tcd:
            start_time = parse_datetime(tcd['start_time'])
            start_time = int(start_time.timestamp())
        end_time = 0
        if "end_time" in tcd:
            end_time = parse_datetime(tcd['end_time'])
            end_time = int(end_time.timestamp())
        csv = None
        if "csv" in tcd:
            csv = tcd['csv']
        strategys = []
        strategys_bunch = []
        if "strategy" in tcd:
            strategy = tcd['strategy']
            strategys.append(strategy)
        elif "strategys" in tcd:
            strategys_list = tcd['strategys'].split(',')
            for st in strategys_list:
                strategy = st
                strategys.append(strategy)
        elif "strategys_bunch" in tcd:
            strategys_list = tcd['strategys_bunch'].split(',')
            for st in strategys_list:
                strategy = st
                strategys_bunch.append(strategy)

        id=0
        if "id" in tcd:
            id = tcd['id']

        auto_download=False
        if "auto_download" in tcd:
            auto_download = tcd['auto_download']

        for si in sis.symbol_intervals:
            if task_type == TaskType.IMPORT_CSV:
                tc,index=new_TaskConfig(id,index,task_type, si, csv, start_time, end_time, None, auto_download)
                ret.append(tc)
            else:
                for strategy in strategys:
                    tc, index = new_TaskConfig(id, index, task_type, si, csv, start_time, end_time, [strategy], auto_download)
                    ret.append(tc)

                if len(strategys_bunch) > 0:
                    tc, index = new_TaskConfig(id, index, task_type, si, csv, start_time, end_time, strategys_bunch,auto_download)
                    ret.append(tc)

    return ret

def get_symbols(tcfgs:[TaskConfig]):
    ret=[]
    for tcfg in tcfgs:
        ret.append(tcfg.symbol_interval.symbol)
    return ret

def get_symbols_from_cfg(cfg):
    return get_symbols(parse_task_config(cfg))

def new_TaskConfig(id,index,task_type, si, csv, start_time, end_time, strategy, auto_download):
    tc = TaskConfig(task_type, si, csv, start_time, end_time, strategy, auto_download)
    if id == 0:
        tc.id = index
        index += 1
    else:
        tc.id = id
    return tc,index