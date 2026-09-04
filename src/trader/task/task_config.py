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
        symbol_interval=SymbolInterval("BTCUSDT", Interval("1d")),
        csv=None,
        start_time=0,
        end_time=0,
        limit=0,
        strategys: [str] = None,
        auto_download=False,
    ):
        self.ttype = ttype
        self.csv = csv
        self.start_time = start_time
        self.end_time = end_time
        self.limit = limit
        self.strategys = strategys
        self.symbol_interval = symbol_interval
        self.auto_download = auto_download

        self.id = id

    def to_dict(self):
        s_time = ""
        if self.start_time > 0:
            s_time = datetime.fromtimestamp(self.start_time)
        e_time = ""
        if self.end_time > 0:
            e_time = datetime.fromtimestamp(self.end_time)
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
            "start_time": f"{s_time}({self.start_time})",
            "end_time": f"{e_time}({self.end_time})",
            "limit": self.limit,
            "strategys": self.strategys,
            "auto_download": self.auto_download,
        }

    def strategy_name(self):
        if self.strategys is None:
            return None
        s = ""
        for st in self.strategys:
            if len(s) > 0:
                s += "+" + st
            else:
                s += st
        return s


# '[{"task_type": "CHECK_KLINES", "start_time": "2023-09-24 14:30:00","end_time":"0","limit":1000,"symbol":"BTCUSDT","interval":"1d",
# "csv":"ETHUSDT-1h-202301-202401.csv","strategy","ShihunRSI2"}]'
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
            tc = TaskConfig(create_task_id(last_task_id), task_type)
            tc.limit = limit
            ret.append(tc)
            last_task_id = tc.id
            continue

        if "symbols" in tcd:
            sis = SymbolsInterval(tcd["symbols"], Interval(tcd["interval"]))
        else:
            sis = SymbolsInterval(tcd["symbol"], Interval(tcd["interval"]))

        start_time = 0

        if "start_time" in tcd:
            stime = parse_datetime(tcd["start_time"])
            start_time = int(stime.timestamp())

        end_time = 0
        if "end_time" in tcd:
            etime = parse_datetime(tcd["end_time"])
            end_time = int(etime.timestamp())
        csv = None
        if "csv" in tcd:
            csv = tcd["csv"]
        strategys = []
        strategys_bunch = []
        if "strategy" in tcd:
            strategy = tcd["strategy"]
            strategys.append(strategy)
        elif "strategys" in tcd:
            strategys_list = tcd["strategys"].split(",")
            for st in strategys_list:
                strategy = st
                strategys.append(strategy)
        elif "strategys_bunch" in tcd:
            strategys_list = tcd["strategys_bunch"].split(",")
            for st in strategys_list:
                strategy = st
                strategys_bunch.append(strategy)

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
                )
                ret.append(tc)
                last_task_id = tc.id
            else:
                for strategy in strategys:
                    tc = TaskConfig(
                        create_task_id(last_task_id),
                        task_type,
                        si,
                        csv,
                        start_time,
                        end_time,
                        limit,
                        [strategy],
                        auto_download,
                    )
                    ret.append(tc)
                    last_task_id = tc.id

                if len(strategys_bunch) > 0:
                    tc = TaskConfig(
                        create_task_id(last_task_id),
                        task_type,
                        si,
                        csv,
                        start_time,
                        end_time,
                        limit,
                        strategys_bunch,
                        auto_download,
                    )
                    ret.append(tc)
                    last_task_id = tc.id

    return ret


def get_symbols(tcfgs: list[TaskConfig]):
    ret = []
    for tcfg in tcfgs:
        ret.append(tcfg.symbol_interval.symbol)
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
