import asyncio
from asyncio import Event, Queue
from logging import Logger
from multiprocessing import Manager, Process

from trader.common.config import Config
from trader.common.message import new_add_tasks_msg
from trader.database.manager import DatabaseManager
from trader.exchange.binance.exchange import BinanceExchange
from trader.task.backtrader_task import BackTraderTask, process_backtrader
from trader.task.base_task import BaseTask
from trader.task.check_klines_num_task import CheckKlinesNumTask
from trader.task.check_klines_task import CheckKlinesTask
from trader.task.debug_task import DebugTask
from trader.task.import_csv_task import ImportCSVTask
from trader.task.task_config import parse_task_config, TaskConfig
from trader.task.task_type import TaskType
from trader.task.trader_task import TraderTask
from trader.task.update_klines_task import UpdateKlinesTask


class TaskManager:
    def __init__(
        self,
        cfg: Config,
        log: Logger,
        db_manager: DatabaseManager,
        exchange: BinanceExchange,
    ):
        self.log = log
        self.cfg = cfg
        self.db_manager = db_manager
        self.exchange = exchange
        self.log.info("Init TaskManager")
        self.tasks: list[BaseTask] = []

    def start(self):
        self.log.info("TaskManager start")
        if self.cfg.tasks:
            taskcs = parse_task_config(self.cfg.tasks)
            if len(taskcs) <= 0:
                return None
            return new_add_tasks_msg(taskcs)
        return None

    def stop(self):
        pass

    async def add_tasks(self, taskcs: list[TaskConfig], queue: Queue, quit: Event):
        if len(taskcs) <= 0:
            self.log.error("Empty task config for add")
            return

        self.log.info(f"Try to add tasks:{len(taskcs)}")

        async_tasks = []
        bttaskcs = []
        for taskc in taskcs:
            if taskc.ttype == TaskType.BACK_TRADER:
                bttaskcs.append(taskc)
        if len(bttaskcs) > 0:
            async_tasks.append(asyncio.create_task(self.add_backtrader_task(bttaskcs, queue, quit)))

        for taskc in taskcs:
            if taskc.ttype == TaskType.BACK_TRADER:
                continue
            async_tasks.append(asyncio.create_task(self.add_task(taskc, queue, quit)))

        self.log.info(f"All tasks are created to running:{len(async_tasks)}")
        await asyncio.gather(*async_tasks)

        for tc in taskcs:
            self.remove_task(tc.id)

    async def add_task(self, cfg, queue: Queue, quit: Event):
        task = None
        if cfg.ttype == TaskType.TRADER:
            task = TraderTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
        elif cfg.ttype == TaskType.BACK_TRADER:
            task = BackTraderTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
        elif cfg.ttype == TaskType.UPDATE_KLINES:
            task = UpdateKlinesTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
        elif cfg.ttype == TaskType.CHECK_KLINES:
            task = CheckKlinesTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
        elif cfg.ttype == TaskType.IMPORT_CSV:
            task = ImportCSVTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
        elif cfg.ttype == TaskType.CHECK_KLINES_NUM:
            task = CheckKlinesNumTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
        elif cfg.ttype == TaskType.DEBUG:
            task = DebugTask(cfg, self.cfg, self.log)

        if task is None:
            self.log.error(f"Can't add task:{cfg.to_dict()}")
            return
        self.tasks.append(task)

        await task.start(queue, quit)

    async def add_backtrader_task(self, cfgs, queue: Queue, quit: Event):
        with Manager() as manager:
            result = manager.list()
            processes = []
            for cfg in cfgs:
                task = BackTraderTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
                self.tasks.append(task)

                ret = await task.start(queue, quit)
                if ret is None:
                    continue
                strategy = ret[0]
                data = ret[1]

                # parmas = manager.list()
                parmas = []
                parmas.append(self.cfg)
                parmas.append(data)
                parmas.append(strategy)
                parmas.append(cfg)

                proc = Process(target=process_backtrader, args=(parmas, result))
                processes.append(proc)

            for p in processes:
                p.start()
            for p in processes:
                p.join()

            for msg in result:
                self.log.info(f"Relay process queue message:{msg.name()}")
                await queue.put(msg)

    def remove_task(self, id: int) -> bool:
        pass
