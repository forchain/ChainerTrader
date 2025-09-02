import asyncio
from asyncio import Queue
from logging import Logger
from multiprocessing import Manager, Process

from trader.common.config import Config
from trader.common.message import new_add_tasks_msg, new_exit_msg
from trader.database.manager import DatabaseManager
from trader.exchange.binance.exchange import BinanceExchange
from trader.task.backtrader_task import BackTraderTask, process_backtrader
from trader.task.base_task import BaseTask
from trader.task.check_klines_num_task import CheckKlinesNumTask
from trader.task.check_klines_task import CheckKlinesTask
from trader.task.debug_task import DebugTask
from trader.task.import_csv_task import ImportCSVTask
from trader.task.task_config import TaskConfig, parse_task_config
from trader.task.task_type import TaskType
from trader.task.trader_task import TraderTask
from trader.task.update_klines_task import UpdateKlinesTask
from trader.utils.task_state import TaskState


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
        self.tasks: dict[int, BaseTask] = {}
        self.async_tasks = []

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

    async def close(self):
        for ts in self.tasks.values():
            ts.close()

        await asyncio.gather(*self.async_tasks)

    def add_tasks(self, taskcs: list[TaskConfig], queue: Queue):
        self.async_tasks.append(asyncio.create_task(self.do_add_tasks(taskcs, queue)))

    async def do_add_tasks(self, taskcs: list[TaskConfig], queue: Queue):
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
            async_tasks.append(asyncio.create_task(self.add_backtrader_task(bttaskcs, queue)))

        for taskc in taskcs:
            if taskc.ttype == TaskType.BACK_TRADER:
                continue
            async_tasks.append(asyncio.create_task(self.add_task(taskc, queue)))

        self.log.info(f"All tasks are created to running:{len(async_tasks)}")
        await asyncio.gather(*async_tasks)

        for tc in taskcs:
            task = self.get_task(tc.id)
            if task:
                task.stop()
                self.tasks.pop(tc.id)

        if not self.cfg.is_server():
            self.log.info("Try to actively exit")
            await queue.put(new_exit_msg())

    async def add_task(self, cfg, queue: Queue):
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
        self.tasks[task.id()] = task

        await task.start(queue)

    async def add_backtrader_task(self, cfgs, queue: Queue):
        with Manager() as manager:
            result = manager.list()
            processes = []
            for cfg in cfgs:
                task = BackTraderTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
                self.tasks[task.id()] = task

                ret = await task.start(queue)
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
                parmas.append(task.ts)
                parmas.append(self.db_manager)

                proc = Process(target=process_backtrader, args=(parmas, result))
                processes.append(proc)

            for p in processes:
                p.start()
            for p in processes:
                p.join()

            for msg in result:
                self.log.info(f"Relay process queue message:{msg.name()}")
                await queue.put(msg)

    def get_task(self, id: int) -> BaseTask | None:
        if id in self.tasks:
            return self.tasks[id]
        return None

    def has_task(self, id: int) -> bool:
        return self.get_task(id) is not None

    def remove_task(self, id: int) -> BaseTask | None:
        if id in self.tasks:
            ret: BaseTask = self.tasks.pop(id)
            if ret:
                self.log.info(f"Remove task:id={id}")
                return ret
        return None

    def close_task(self, id: int):
        task = self.get_task(id)
        if task:
            task.close()
            return True
        return False

    def get_task_state(self, id: int) -> TaskState | None:
        task = self.get_task(id)
        if task:
            return task.ts
        if self.db_manager:
            return self.db_manager.task.get_task(id)

        return None

    def get_all_task_state(self) -> list[TaskState]:
        ret: list[TaskState] = []
        for ts in self.tasks.values():
            ret.append(ts.ts)

        if self.db_manager:
            tss = self.db_manager.task.get_all_tasks()
            for ts in tss:
                if self.has_task(ts.id):
                    continue
                ret.append(ts)

        return ret
