import os
from datetime import datetime
import datetime as dt

from trader.app.database_manager import DatabaseManager
from trader.binance.csvdata import BinanceCSVData
from trader.binance.data import BinanceData
from trader.common import path
from trader.strategy.node import Node
from trader.strategy.strategy import StrategyType, parseStrategy
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from asyncio import Queue, Event
import csv

from trader.utils.kline import Kline


class ImportCSVTask:
    def __init__(self,tcfg:TaskConfig,cfg,log,db_manager:DatabaseManager):
        self.log = log
        self.cfg=cfg
        self.tcfg = tcfg
        self.db_manager = db_manager
        self.log.info(f"Init {self.name()}")

    async def start(self,queue:Queue,quit:Event):
        self.start_time = datetime.now()
        if not self.cfg.data_file:
            self.log.error(f"{self.name()} no data_file")
            return
        self.log.info(f"Start {self.name()}")
        kls = []
        data_file = self.cfg.data_file
        if not os.path.isabs(self.cfg.data_file):
            data_file = os.path.join(path.GetDatasDir(), self.cfg.data_file)

        with open(data_file, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.reader(file)
            next(reader)
            for row in reader:
                if len(row) != 12:
                    continue
                open_time,openp,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore = row
                kls.append(Kline(int(int(open_time)/1000),float(openp),float(high),float(low),float(close),int(int(close_time)/1000),
                                 float(volume),float(quote_volume),int(count),
                                 float(taker_buy_volume),float(taker_buy_quote_volume),float(ignore)))

        if len(kls) <= 0:
            self.log.error(f"No kline in {data_file}")
            return
        self.log.info(f"Read klines ({len(kls)}) from {data_file}")

        collection = self.db_manager.get_collection("trader", self.tcfg.symbol_interval.name())

        ret = self.db_manager.add_klines(collection, kls)
        if ret != len(kls):
            self.log.warning(f"{self.name()} add klines to DB: {ret} != {len(kls)}")
        else:
            self.log.info(f"{self.name()} add klines to DB: {ret}")

        self.stop()

    def stop(self):
        elapsed = datetime.now() - self.start_time
        self.log.info(f"Stop {self.name()}, elapsed time:{elapsed}")

    def name(self):
        return f"{self.type()}({self.tcfg.symbol_interval.name()})"

    def type(self):
        return TaskType.IMPORT_CSV