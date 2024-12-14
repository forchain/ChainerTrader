import asyncio
from asyncio import Queue, Event
from logging import Logger

from trader.app.database_manager import DatabaseManager
from trader.common.message import Message, new_task_msg
from trader.task.check_klines_task import CheckKlinesTask
from trader.task.task_config import parse_task_config, TaskConfig
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

    def start(self,queue:Queue,quit:Event)->[]:
        ret=[]
        if not self.cfg.check_symbols_intervals():
            self.log.error(f"symbols intervals error")
            return ret
        taskcs = parse_task_config(self.cfg.tasks)

        for si in self.cfg.get_symbol_interval_list():
            for taskc in taskcs:
                if taskc.type == TaskType.BACK_TRADER:
                    if not self.cfg.data_file:
                        self.log.error(f"No config data_file for {taskc.to_dict()}")
                        continue
                else:
                    if not self.exchange:
                        self.log.error(f"No config exchange for {taskc.to_dict()}")
                        continue
                    if not self.db_manager:
                        self.log.error(f"No config db_uri for {taskc.to_dict()}")
                        continue
                taskc.symbol_interval=si
                ret.append(asyncio.create_task(self.add_task(taskc,queue,quit)))
        return ret

    def stop(self):
        pass

    async def add_task(self,cfg,queue:Queue,quit:Event):
        task=None
        if cfg.type == TaskType.TRADER:
            task=TraderTask(cfg,self.cfg, self.log, self.db_manager, self.exchange)
        elif cfg.type == TaskType.BACK_TRADER:
            task =BackTraderTask(cfg,self.cfg, self.log)
        elif cfg.type == TaskType.UPDATE_KLINES:
            task =UpdateKlinesTask(cfg,self.cfg, self.log, self.db_manager, self.exchange)
        elif cfg.type == TaskType.CHECK_KLINES:
            task=CheckKlinesTask(cfg,self.cfg, self.log, self.db_manager, self.exchange)

        if task is None:
            self.log.error(f"Can't add task:{cfg.to_dict()}")
            return
        await task.start(queue,quit)