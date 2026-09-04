from logging import Logger

from trader.app.database_manager import DatabaseManager
from trader.binance.exchange import BinanceExchange
from trader.common.config import Config
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import SymbolInterval

class CheckKlinesTask:
    def __init__(self,cfg:Config,log:Logger,db_manager:DatabaseManager,exchange:BinanceExchange):
        self.log = log
        self.cfg = cfg
        self.db_manager = db_manager
        self.exchange = exchange
        self.symbol_interval:SymbolInterval=self.cfg.get_symbol_interval_list()[0]
        self.log.info(f"Init {self.name()}")

    def start(self):
        pass

    def stop(self):
        pass

    def name(self):
        return f"{self.type()}({self.symbol_interval.name()})"

    def type(self):
        return TaskType.CHECK_KLINES