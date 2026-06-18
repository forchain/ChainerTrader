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


def _task_config_symbol(symbol_interval) -> str:
    symbol = getattr(symbol_interval, "sy", None)
    base = getattr(symbol, "base", "")
    quote = getattr(symbol, "quote", "")
    if base and quote:
        return f"{base}-{quote}"
    return symbol_interval.symbol()


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
            user_id=getattr(tcfg, "user_id", None),
        )

    def _generate_config_json(self) -> str:
        """Generate JSON configuration for easy copying"""
        config_dict = {
            "task_type": self.tcfg.ttype.name,
        }
        if self.tcfg.symbol_interval:
            config_dict["symbol"] = _task_config_symbol(self.tcfg.symbol_interval)
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
        if getattr(self.tcfg, "live_trade_max_notional", 0.0):
            config_dict["live_trade_max_notional"] = self.tcfg.live_trade_max_notional
        if getattr(self.tcfg, "live_short_execution", "disabled") != "disabled":
            config_dict["live_short_execution"] = self.tcfg.live_short_execution
        if getattr(self.tcfg, "live_margin_borrow_block_policy", "skip_continue") != "skip_continue":
            config_dict["live_margin_borrow_block_policy"] = self.tcfg.live_margin_borrow_block_policy
        if getattr(self.tcfg, "live_margin_borrow_precheck", True) is not True:
            config_dict["live_margin_borrow_precheck"] = self.tcfg.live_margin_borrow_precheck
        if getattr(self.tcfg, "live_margin_auto_repay_max_total", 100.0) != 100.0:
            config_dict["live_margin_auto_repay_max_total"] = self.tcfg.live_margin_auto_repay_max_total
        if getattr(self.tcfg, "live_margin_auto_repay_max_per_asset", 50.0) != 50.0:
            config_dict["live_margin_auto_repay_max_per_asset"] = self.tcfg.live_margin_auto_repay_max_per_asset
        if getattr(self.tcfg, "live_margin_auto_repay_min_amount", 0.000001) != 0.000001:
            config_dict["live_margin_auto_repay_min_amount"] = self.tcfg.live_margin_auto_repay_min_amount
        if getattr(self.tcfg, "live_margin_auto_repay_excluded_assets", None):
            config_dict["live_margin_auto_repay_excluded_assets"] = list(self.tcfg.live_margin_auto_repay_excluded_assets)
        if getattr(self.tcfg, "strategy_params", None):
            config_dict["strategy_params"] = self.tcfg.strategy_params
        if getattr(self.tcfg, "requires_short_capability", False):
            config_dict["requires_short_capability"] = True
        if getattr(self.tcfg, "user_id", None) is not None:
            config_dict["user_id"] = self.tcfg.user_id
        if getattr(self.tcfg, "run_id", None):
            config_dict["run_id"] = self.tcfg.run_id
        if getattr(self.tcfg, "fund_reservation_asset", None):
            config_dict["fund_reservation_asset"] = self.tcfg.fund_reservation_asset
        if getattr(self.tcfg, "fund_reservation_amount", None) is not None:
            config_dict["fund_reservation_amount"] = self.tcfg.fund_reservation_amount
        if getattr(self.tcfg, "fund_reservation_remaining", None) is not None:
            config_dict["fund_reservation_remaining"] = self.tcfg.fund_reservation_remaining

        return json.dumps([config_dict], indent=2, ensure_ascii=False)

    def start(self, queue: Queue):
        self.start_time = datetime.now()
        self.log.info(f"Start {self.name()}")
        self.ts.state = TaskStateType.RUNNING
        return self._persist_state()

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

    def _persist_state(self):
        task_store = getattr(self.db_manager, "task", None)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if task_store is None:
            if loop is not None:
                return asyncio.sleep(0)
            return

        async def _save():
            await task_store.add_tasks([self.ts])

        if loop is None:
            asyncio.run(_save())
        else:
            return loop.create_task(_save())
