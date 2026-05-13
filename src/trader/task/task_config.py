import json
import os
from datetime import datetime

from trader.common import path
from trader.common.common import parse_datetime
from trader.task.optimization import expand_parameter_space, has_parameter_search, make_optimization_run_id, make_param_id
from trader.task.task_type import TaskType, parse_task_type
from trader.live.auto_execution import (
    normalize_live_execution_mode,
    normalize_live_short_execution,
    normalize_margin_borrow_block_policy,
)
from trader.utils.symbol_interval import Interval, SymbolInterval
from trader.utils.symbols_interval import SymbolsInterval


def normalize_strategy_params(params: dict) -> dict:
    normalized = dict(params)

    enter_key = "chainer_enter_need_confirm"
    exit_key = "chainer_exit_need_confirm"
    merged_key = "chainer_need_confirm"

    has_enter = enter_key in normalized
    has_exit = exit_key in normalized

    if has_enter or has_exit:
        enter_value = normalized.get(enter_key)
        exit_value = normalized.get(exit_key)
        if has_enter and has_exit and enter_value != exit_value:
            raise ValueError("chainer_enter_need_confirm and chainer_exit_need_confirm must match")
        merged_value = enter_value if has_enter else exit_value
        normalized[merged_key] = merged_value
        normalized.pop(enter_key, None)
        normalized.pop(exit_key, None)

    normalized.pop("chainer_auto_signal", None)
    normalized.pop("chainer_signal_interfaces", None)
    return normalized


def infer_strategy_requires_short(strategy_params: dict | None, live_short_execution: str | None = None) -> bool:
    params = dict(strategy_params or {})
    mode = params.get("chainer_mode")
    if mode is not None:
        return str(mode).strip().upper() in {"SHORT_ONLY", "BOTH"}
    return str(live_short_execution or "disabled").strip().lower() == "margin_cross"


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
        force_update: bool = False,
        strategy_params: dict | None = None,
        param_id: str | None = None,
        optimization_run_id: str | None = None,
        dataset_ref=None,
        live_execution_mode: str = "auto_trade",
        manual_start_position: float = 0.0,
        live_data_mode: str = "polling",
        live_trade_max_notional: float = 0.0,
        live_short_execution: str = "disabled",
        live_margin_borrow_block_policy: str = "auto_repay_then_retry_once",
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
        self.force_update = force_update
        self.strategy_params = strategy_params or {}
        self.param_id = param_id
        self.optimization_run_id = optimization_run_id
        self.dataset_ref = dataset_ref
        self.live_execution_mode = normalize_live_execution_mode(live_execution_mode)
        self.manual_start_position = float(manual_start_position or 0.0)
        self.live_data_mode = str(live_data_mode or "polling").strip().lower()
        self.live_trade_max_notional = float(live_trade_max_notional or 0.0)
        self.live_short_execution = normalize_live_short_execution(live_short_execution)
        self.live_margin_borrow_block_policy = normalize_margin_borrow_block_policy(live_margin_borrow_block_policy)
        self.requires_short_capability = infer_strategy_requires_short(self.strategy_params, self.live_short_execution)

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
            "force_update": self.force_update,
            "strategy_params": self.strategy_params,
            "param_id": self.param_id,
            "optimization_run_id": self.optimization_run_id,
            "live_execution_mode": self.live_execution_mode,
            "manual_start_position": self.manual_start_position,
            "live_data_mode": self.live_data_mode,
            "live_trade_max_notional": self.live_trade_max_notional,
            "live_short_execution": self.live_short_execution,
            "live_margin_borrow_block_policy": self.live_margin_borrow_block_policy,
            "requires_short_capability": self.requires_short_capability,
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
    optimization_run_id = None
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

        if "start_time" in tcd:
            stime = parse_datetime(tcd["start_time"])
            start_time = int(stime.timestamp())
        else:
            start_time = int(parse_datetime("2000-01-01 00:00:00").timestamp())

        if "end_time" in tcd:
            etime = parse_datetime(tcd["end_time"])
            end_time = int(etime.timestamp())
        else:
            end_time = int(datetime.now().timestamp())

        free = -1
        if "free" in tcd:
            free = float(tcd["free"])

        live_execution_mode = normalize_live_execution_mode(tcd.get("live_execution_mode", "auto_trade"))
        manual_start_position = float(tcd.get("manual_start_position", 0.0) or 0.0)
        live_data_mode = str(tcd.get("live_data_mode", "polling")).strip().lower()
        live_trade_max_notional = float(tcd.get("live_trade_max_notional", 0.0) or 0.0)
        live_short_execution = normalize_live_short_execution(tcd.get("live_short_execution", "disabled"))
        live_margin_borrow_block_policy = normalize_margin_borrow_block_policy(
            tcd.get("live_margin_borrow_block_policy", "auto_repay_then_retry_once")
        )

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

        force_update = False
        if "force_update" in tcd:
            force_update = tcd["force_update"]

        parameter_search_enabled = has_parameter_search(tcd)
        if parameter_search_enabled:
            strategy_count = len(strategies) + len(strategies_bunch)
            if strategy_count != 1:
                raise ValueError("parameter search requires a single strategy entry")
            if optimization_run_id is None:
                optimization_run_id = tcd.get("optimization_run_id") or os.environ.get("TRADER_OPTIMIZATION_RUN_ID") or make_optimization_run_id()
            auto_download = tcd.get("auto_download", True)
            parameter_sets = expand_parameter_space(tcd)
        else:
            parameter_sets = [dict(tcd.get("strategy_params", {}) or {})]

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
                    force_update,
                    strategy_params={},
                    live_execution_mode=live_execution_mode,
                    manual_start_position=manual_start_position,
                    live_data_mode=live_data_mode,
                    live_trade_max_notional=live_trade_max_notional,
                    live_short_execution=live_short_execution,
                    live_margin_borrow_block_policy=live_margin_borrow_block_policy,
                )
                ret.append(tc)
                last_task_id = tc.id
            else:
                for strategy in strategies:
                    for strategy_params in parameter_sets:
                        normalized_params = normalize_strategy_params(strategy_params)
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
                            free,
                            force_update,
                            strategy_params=normalized_params,
                            param_id=make_param_id(normalized_params) if parameter_search_enabled else None,
                            optimization_run_id=optimization_run_id if parameter_search_enabled else None,
                            live_execution_mode=live_execution_mode,
                            manual_start_position=manual_start_position,
                            live_data_mode=live_data_mode,
                            live_trade_max_notional=live_trade_max_notional,
                            live_short_execution=live_short_execution,
                            live_margin_borrow_block_policy=live_margin_borrow_block_policy,
                        )
                        ret.append(tc)
                        last_task_id = tc.id

                if len(strategies_bunch) > 0:
                    tc = TaskConfig(
                        create_task_id(last_task_id),
                        task_type,
                        si,
                        csv,
                        start_time,
                        end_time,
                        limit,
                        strategies_bunch,
                        auto_download,
                        free,
                        force_update,
                        strategy_params={},
                        live_execution_mode=live_execution_mode,
                        manual_start_position=manual_start_position,
                        live_data_mode=live_data_mode,
                        live_trade_max_notional=live_trade_max_notional,
                        live_short_execution=live_short_execution,
                        live_margin_borrow_block_policy=live_margin_borrow_block_policy,
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
