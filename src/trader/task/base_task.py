import asyncio
import json
from asyncio import Event, Queue
from datetime import datetime

from trader.common.config import Config
from trader.common.logger import Logger
from trader.database.manager import DatabaseManager
from trader.exchange.binance.exchange import BinanceExchange
from trader.task.task_config import TaskConfig
from trader.utils.task_state import TaskState, TaskStateType


class BaseTask:
    def __init__(
        self,
        tcfg: TaskConfig,
        cfg: Config,
        log: Logger,
        db_manager: DatabaseManager = None,
        exchange: BinanceExchange = None,
    ):
        self.log = log
        self.cfg = cfg
        self.db_manager = db_manager
        self.exchange = exchange
        self.tcfg = tcfg
        self.log.info(f"Init {self.name()}")
        self.start_time = datetime.now()
        self.quit: Event = asyncio.Event()

        # Generate config JSON for display
        config_json = self._generate_config_json()

        self.ts = TaskState(
            tcfg.id,
            self.name(),
            self.start_time,
            None,
            self.cfg.commission,
            strategy_start_time=tcfg.start_time,
            strategy_end_time=tcfg.end_time,
            initial_cash=cfg.cash if tcfg.free < 0 else tcfg.free,
            config_json=config_json,
        )

    def _generate_config_json(self) -> str:
        """Generate JSON configuration for easy copying"""
        config_dict = {
            "task_type": self.tcfg.ttype.name,
        }
        if self.tcfg.symbol_interval:
            config_dict["symbol"] = self.tcfg.symbol_interval.symbol()
            config_dict["interval"] = self.tcfg.symbol_interval.interval.value

        if self.tcfg.csv:
            config_dict["csv"] = self.tcfg.csv

        if self.tcfg.start_time > 0:
            config_dict["start_time"] = datetime.fromtimestamp(self.tcfg.start_time).strftime("%Y-%m-%d %H:%M:%S")

        if self.tcfg.end_time > 0:
            config_dict["end_time"] = datetime.fromtimestamp(self.tcfg.end_time).strftime("%Y-%m-%d %H:%M:%S")

        if self.tcfg.strategies:
            if len(self.tcfg.strategies) == 1:
                config_dict["strategy"] = self.tcfg.strategies[0]
            else:
                config_dict["strategies"] = ",".join(self.tcfg.strategies)

        if self.tcfg.auto_download:
            config_dict["auto_download"] = True

        if self.tcfg.free >= 0:
            config_dict["free"] = self.tcfg.free
        if getattr(self.tcfg, "live_execution_mode", "auto_trade") != "auto_trade":
            config_dict["live_execution_mode"] = self.tcfg.live_execution_mode
        if getattr(self.tcfg, "live_data_mode", "polling") != "polling":
            config_dict["live_data_mode"] = self.tcfg.live_data_mode
        if getattr(self.tcfg, "manual_start_position", 0.0):
            config_dict["manual_start_position"] = self.tcfg.manual_start_position
        if getattr(self.tcfg, "strategy_params", None):
            config_dict["strategy_params"] = self.tcfg.strategy_params

        return json.dumps([config_dict], indent=2, ensure_ascii=False)

    def start(self, queue: Queue):
        self.start_time = datetime.now()
        self.log.info(f"Start {self.name()}")
        self.ts.state = TaskStateType.RUNNING

    def stop(self):
        if not self.ts.is_running():
            return
        self.ts.state = TaskStateType.DONE
        self.close()
        elapsed = datetime.now() - self.start_time
        self.log.info(f"Stop {self.name()}, elapsed time:{elapsed}")

    def name(self):
        return f"{self.tcfg.id}.{self.type().name}.{self.tcfg.symbol_interval.name()}"

    def type(self):
        return self.tcfg.ttype

    def id(self) -> int:
        return self.tcfg.id

    def close(self):
        self.quit.set()
