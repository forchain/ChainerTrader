import json
import os
from datetime import datetime

from trader.common import path
from trader.common.common import parse_datetime
from trader.task.task_type import TaskType, parse_task_type
from trader.utils.symbol_interval import Interval, SymbolInterval
from trader.utils.symbols_interval import SymbolsInterval


class TaskConfig:
    def __init__(
        self,
        id: int,
        ttype: TaskType,
        symbol_interval=SymbolInterval("BTC-USDT", Interval("1d")),
        csv=None,
        start_time=0,
        end_time=0,
        limit=0,
        strategies: [str] = None,
        auto_download=False,
        free: float = -1,
    ):
        self.ttype = ttype
        self.csv = csv
        self.start_time = start_time
        self.end_time = end_time
        self.limit = limit
        self.strategies = strategies
        self.symbol_interval = symbol_interval
        self.auto_download = auto_download
        self.free = free

        self.id = id

    def to_dict(self):
        s_time = "not speicifed"
        if self.start_time > 0:
            s_time = f"{datetime.fromtimestamp(self.start_time)}({self.start_time})"

        e_time = "not speicifed"
        if self.end_time > 0:
            e_time = f"{datetime.fromtimestamp(self.end_time)}({self.end_time})"

        limit_str = "not speicifed"
        if self.limit > 0:
            limit_str = f"{self.limit}"

        if self.ttype == TaskType.DEBUG:
            return {
                "id": self.id,
                "type": self.ttype,
                "limit": self.limit,
            }
        return {
            "id": self.id,
            "type": self.ttype,
            "symbol_interval": self.symbol_interval.name(),
            "csv": self.csv,
            "start_time": f"{s_time}",
            "end_time": f"{e_time}",
            "limit": f"{limit_str}",
            "strategies": self.strategies,
            "auto_download": self.auto_download,
            "free": self.free,
        }

    def strategy_name(self):
        if self.strategies is None:
            return None
        s = ""
        for st in self.strategies:
            if len(s) > 0:
                s += "+" + st
            else:
                s += st
        return s


# '[{"task_type": "CHECK_KLINES", "start_time": "2023-09-24 14:30:00","end_time":"0","limit":1000,"symbol":"BTC-USDT","interval":"1d",
# "csv":"ETHUSDT-1h-202301-202401.csv","strategy":"ShihunRSI2","free":100}]'
def parse_task_config(cfg: str, last_task_id: int = 0) -> list[TaskConfig]:
    file_path = path.get_file_path(cfg)
    if os.path.isfile(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                parsed_list = json.load(file)
        except json.JSONDecodeError:
            return []
        except FileNotFoundError:
            return []
    else:
        parsed_list = json.loads(cfg)

    ret = []
    for tcd in parsed_list:
        task_type = parse_task_type(tcd["task_type"])

        limit = 0
        if "limit" in tcd:
            limit = tcd["limit"]

        if task_type == TaskType.DEBUG:
            tc = TaskConfig(create_task_id(last_task_id), task_type, None)
            tc.limit = limit
            ret.append(tc)
            last_task_id = tc.id
            continue

        if "symbols" in tcd:
            sis = SymbolsInterval(tcd["symbols"], Interval(tcd["interval"]))
        else:
            sis = SymbolsInterval(tcd["symbol"], Interval(tcd["interval"]))
        if len(sis) <= 0:
            continue

        start_time = 0

        if "start_time" in tcd:
            stime = parse_datetime(tcd["start_time"])
            start_time = int(stime.timestamp())

        end_time = 0
        if "end_time" in tcd:
            etime = parse_datetime(tcd["end_time"])
            end_time = int(etime.timestamp())

        free = -1
        if "free" in tcd:
            free = float(tcd["free"])

        csv = None
        if "csv" in tcd:
            csv = tcd["csv"]
        strategies = []
        strategies_bunch = []
        if "strategy" in tcd:
            strategy = tcd["strategy"]
            strategies.append(strategy)
        elif "strategies" in tcd:
            strategies_list = tcd["strategies"].split(",")
            for st in strategies_list:
                strategy = st
                strategies.append(strategy)
        elif "strategies_bunch" in tcd:
            strategies_list = tcd["strategies_bunch"].split(",")
            for st in strategies_list:
                strategy = st
                strategies_bunch.append(strategy)

        auto_download = False
        if "auto_download" in tcd:
            auto_download = tcd["auto_download"]

        for si in sis.symbol_intervals:
            if (
                task_type == TaskType.IMPORT_CSV
                or task_type == TaskType.CHECK_KLINES
                or task_type == TaskType.CHECK_KLINES_NUM
                or task_type == TaskType.UPDATE_KLINES
            ):
                tc = TaskConfig(
                    create_task_id(last_task_id),
                    task_type,
                    si,
                    csv,
                    start_time,
                    end_time,
                    limit,
                    None,
                    auto_download,
                    free,
                )
                ret.append(tc)
                last_task_id = tc.id
            else:
                for strategy in strategies:
                    tc = TaskConfig(create_task_id(last_task_id), task_type, si, csv, start_time, end_time, limit, [strategy], auto_download, free)
                    ret.append(tc)
                    last_task_id = tc.id

                if len(strategies_bunch) > 0:
                    tc = TaskConfig(
                        create_task_id(last_task_id), task_type, si, csv, start_time, end_time, limit, strategies_bunch, auto_download, free
                    )
                    ret.append(tc)
                    last_task_id = tc.id

    return ret


def get_symbols(tcfgs: list[TaskConfig]):
    ret = []
    for tcfg in tcfgs:
        ret.append(tcfg.symbol_interval.symbol())
    return ret


def get_symbols_from_cfg(cfg):
    return get_symbols(parse_task_config(cfg))


def create_task_id(last_task_id: int) -> int:
    current_timestamp = datetime.now().timestamp()
    task_id = int(current_timestamp * 1000)
    while True:
        if task_id > last_task_id:
            return task_id
        task_id += 1
