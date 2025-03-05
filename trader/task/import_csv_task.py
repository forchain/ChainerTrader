import os
from datetime import datetime
import datetime as dt

from trader.app.database_manager import DatabaseManager
from trader.binance.csvdata import BinanceCSVData
from trader.binance.data import BinanceData
from trader.binance.exchange import BinanceExchange
from trader.common import path
from trader.strategy.node import Node
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from asyncio import Queue, Event
import csv

from trader.utils.kline import Kline
from trader.utils.symbol_interval import add_time_duration


class ImportCSVTask(BaseTask):
    def __init__(self,tcfg:TaskConfig,cfg,log,db_manager:DatabaseManager,exchange:BinanceExchange):
        super().__init__(tcfg, cfg, log, db_manager, exchange)

    async def start(self,queue:Queue,quit:Event):
        if not self.tcfg.csv:
            self.log.error(f"No config data_file for {self.tcfg.to_dict()}")
            return
        if not self.db_manager:
            self.log.error(f"No config db_uri for {self.tcfg.to_dict()}")
            return

        super().start(queue,quit)

        if not self.tcfg.csv:
            self.log.error(f"{self.name()} no data_file")
            return

        kls = []
        data_file = self.tcfg.csv
        if not os.path.isabs(self.tcfg.csv):
            data_file = os.path.join(path.GetDatasDir(), self.tcfg.csv)

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
        if len(kls) >= 2:
            next_open_time = add_time_duration(kls[0].open_time, self.tcfg.symbol_interval.interval, 1)
            if next_open_time != kls[1].open_time:
                self.log.error(f"{self.name()} kline interval is not {self.tcfg.symbol_interval.interval.name}")
                return


        collection = self.db_manager.get_collection(self.cfg.db_name, self.tcfg.symbol_interval.name())

        ret = self.db_manager.add_klines(collection, kls)
        if ret != len(kls):
            self.log.warning(f"{self.name()} add klines to DB: {ret} != {len(kls)}")
        else:
            self.log.info(f"{self.name()} add klines to DB: {ret}")

        self.stop()