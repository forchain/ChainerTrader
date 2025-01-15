import asyncio
from asyncio import Queue, Event
from logging import Logger
from multiprocessing import Manager, Process

from trader.app.database_manager import DatabaseManager
from trader.common.common import sleep
from trader.common.message import new_stat_msg
from trader.statistics.stat import BackTraderStat
from trader.statistics.statistics import Statistics
from trader.task.check_klines_task import CheckKlinesTask
from trader.task.import_csv_task import ImportCSVTask
from trader.task.task_config import parse_task_config, TaskConfig
from trader.task.trader_task import TraderTask
from trader.task.backtrader_task import BackTraderTask, process_backtrader
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
        taskcs = parse_task_config(self.cfg.tasks)
        self.log.info(f"Load task config:{len(taskcs)}")

        ret = []
        bttaskcs = []
        index = 0
        for taskc in taskcs:
            if taskc.ttype == TaskType.BACK_TRADER:
                taskc.id=index
                index+=1
                bttaskcs.append(taskc)
        if len(bttaskcs) > 0:
            ret.append(asyncio.create_task(self.add_backtrader_task(bttaskcs,queue,quit)))

        for taskc in taskcs:
            if taskc.ttype == TaskType.BACK_TRADER:
                continue
            taskc.id = index
            index += 1
            ret.append(asyncio.create_task(self.add_task(taskc, queue, quit)))

        return ret

    def stop(self):
        pass

    async def add_task(self,cfg,queue:Queue,quit:Event):
        task=None
        if cfg.ttype == TaskType.TRADER:
            task=TraderTask(cfg,self.cfg, self.log, self.db_manager, self.exchange)
        elif cfg.ttype == TaskType.BACK_TRADER:
            task =BackTraderTask(cfg,self.cfg, self.log,self.db_manager,self.exchange)
        elif cfg.ttype == TaskType.UPDATE_KLINES:
            task =UpdateKlinesTask(cfg,self.cfg, self.log, self.db_manager, self.exchange)
        elif cfg.ttype == TaskType.CHECK_KLINES:
            task=CheckKlinesTask(cfg,self.cfg, self.log, self.db_manager,self.exchange)
        elif cfg.ttype == TaskType.IMPORT_CSV:
            task =ImportCSVTask(cfg,self.cfg, self.log,self.db_manager,self.exchange)

        if task is None:
            self.log.error(f"Can't add task:{cfg.to_dict()}")
            return
        await task.start(queue,quit)


    async def add_backtrader_task(self,cfgs,queue:Queue,quit:Event):
        with Manager() as manager:
            result = manager.list()
            processes = []
            tasks = []
            for cfg in cfgs:
                task = BackTraderTask(cfg,self.cfg,self.log,self.db_manager,self.exchange)
                strategy,data = task.start(queue,quit)
                tasks.append(task)

                #parmas = manager.list()
                parmas=[]
                parmas.append(self.cfg)
                parmas.append(data)
                parmas.append(strategy)
                parmas.append(cfg)


                proc = Process(target=process_backtrader,args=(parmas,result))
                processes.append(proc)

            for p in processes:
                p.start()
            for p in processes:
                p.join()

            for msg in result:
                self.log.info(f"Relay process queue message:{msg.name()}")
                await queue.put(msg)

        for task in tasks:
            task.stop()
