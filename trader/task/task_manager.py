from logging import Logger

from trader.app.database_manager import DatabaseManager
from trader.task.trader_task import TraderTask
from trader.task.backtrader_task import BackTraderTask
from trader.binance.exchange import BinanceExchange
from trader.common.config import Config
from trader.task.task_type import parse_task_type, TaskType
from trader.task.update_klines_task import UpdateKlinesTask
from trader.utils.trend import TrendType


class TaskManager:
    def __init__(self,cfg:Config,log:Logger,db_manager:DatabaseManager,exchange:BinanceExchange):
        self.log = log
        self.cfg = cfg
        self.db_manager = db_manager
        self.exchange = exchange
        self.log.info(f"Init TaskManager")
        self.tasks = []

    def start(self):
        if not self.cfg.check_symbols_intervals():
            self.log.error(f"symbols intervals error")
            return
        taskType=parse_task_type(self.cfg.task)
        if taskType == TaskType.TRADER:
            if self.cfg.exchange:
                self.tasks.append(TraderTask(self.cfg, self.log, self.db_manager, self.exchange))
        elif taskType == TaskType.BACK_TRADER:
            if self.cfg.data_file:
                self.tasks.append(BackTraderTask(self.cfg, self.log))
        elif taskType == TaskType.UPDATE_KLINES:
            if self.cfg.exchange:
                self.tasks.append(UpdateKlinesTask(self.cfg, self.log, self.db_manager, self.exchange))

        for task in self.tasks:
            task.start()

    def stop(self):
        for task in self.tasks:
            task.stop()

    def add_task(self,task):
        pass