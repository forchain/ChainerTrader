import asyncio
import os
import signal
from asyncio import Event
from datetime import datetime

from trader.common import path
from trader.common.common import NAME
from trader.common.config import Config, default
from trader.common.logger import Logger
from trader.common.message import Message, new_add_tasks_msg, new_exit_msg
from trader.database.manager import DatabaseManager
from trader.exchange.binance.exchange import BinanceExchange
from trader.exchange.exchange_config import parse_exchange_config
from trader.exchange.exchange_type import ExchangeType
from trader.notify.notify_manager import NotifyManager
from trader.statistics.statistics import Statistics
from trader.task.task_config import parse_task_config, TaskConfig
from trader.task.task_manager import TaskManager


class App:
    def __init__(self, cfg: Config = default()):
        self.cfg = cfg
        self.logger = Logger(cfg)

        self.log().info(f"Init App {self.name()}")

        self.db_manager = None
        self.exchange = None

        if self.cfg.db:
            self.db_manager = DatabaseManager(cfg, self.logger)

        if self.cfg.exchange:
            ex_cfg = parse_exchange_config(self.cfg.exchange)
            if ex_cfg and ex_cfg.ty == ExchangeType.BINANCE:
                self.exchange = BinanceExchange(ex_cfg, self.log())

        self.notify_mgr = NotifyManager(cfg, self.logger)

        self.stat = Statistics(self.cfg, self.log())
        self.task_manager = TaskManager(self.cfg, self.log(), self.db_manager, self.exchange)

        self.startTime = datetime.now()
        self.queue = None

    def name(self):
        return NAME

    def log(self):
        return self.logger.log()

    def get_running_mode(self) -> str:
        if self.cfg.is_server():
            return "server"
        return "CLI"

    def start(self):
        self.log().info(f"Start {self.name()} App, config:{self.cfg.to_dict()}, running mode:{self.get_running_mode()}")

        if not self.cfg.is_server():
            if self.cfg.tasks is None:
                self.log().warn("No tasks can be executed")
                return False

        self.notify_mgr.start()

        if self.db_manager:
            self.db_manager.start()
        if self.exchange:
            self.exchange.start()

        msgs: list[Message] = []
        if self.task_manager:
            msg = self.task_manager.start()
            if msg:
                msgs.append(msg)

        self.process(msgs)
        return True

    def stop(self):
        self.stat.report()

        if self.task_manager:
            self.task_manager.stop()

        if self.db_manager:
            self.db_manager.stop()
        if self.exchange:
            self.exchange.stop()

        elapsed = datetime.now() - self.startTime
        self.log().info(f"Stop {self.name()} App, elapsed time:{elapsed}")

    def version(self):
        return version()

    def info(self):
        return {
            "name": self.name(),
            "version": self.version(),
            "commission": self.cfg.commission,
            "period": self.cfg.period,
            "atr": self.cfg.atr,
            "mode": self.get_running_mode(),
        }

    def config(self):
        return self.cfg

    def process(self, msgs: list[Message]):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        quit = asyncio.Event()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.shutdown, quit)
        try:
            loop.run_until_complete(self.handler(msgs, quit))
        except asyncio.CancelledError:
            self.log().debug("All tasks have been cancelled.")
        finally:
            loop.close()
            self.log().info(f"{self.name()} tasks exited.")

    def shutdown(self, quit: Event):
        self.log().info(f"Received shutdown signal, stopping {self.name()}...")
        self.exit_handle(quit)

    async def handler(self, msgs: list[Message], quit: Event):
        queue = asyncio.Queue()
        self.queue = queue

        for msg in msgs:
            await queue.put(msg)

        self.log().info(f"{self.name()} enter handler: init messages={len(msgs)}")

        while True:
            msg: Message = await queue.get()
            self.log().debug(f"Processing message: {msg.name()}")
            if msg.is_exit():
                self.log().info("Received exit message, shutting down...")
                break
            elif msg.is_stat():
                self.stat.handler(msg)
                self.notify_mgr.handler(msg)

            elif msg.is_add_tasks():
                await self.task_manager.add_tasks(msg.get_data(), queue, quit)
                if not self.cfg.is_server():
                    self.exit_handle(quit)

            queue.task_done()

        self.log().info(f"{self.name()} exit handler")

    def exit_handle(self, quit: Event):
        quit.set()
        self.send_exit_msg()

    def send_exit_msg(self):
        if self.queue:
            try:
                self.queue.put_nowait(new_exit_msg())
            except asyncio.QueueFull:
                self.log().error("QueueFull")

    def send_add_tasks_msg(self, tasks_cfg: str):
        taskcs: list[TaskConfig] = []
        if tasks_cfg:
            taskcs = parse_task_config(tasks_cfg)

        if len(taskcs) <= 0:
            return {
                "result": "fail",
                "error": "The input parameter is empty",
            }

        msg = new_add_tasks_msg(taskcs)

        self.queue.put_nowait(msg)

        ids = []
        for tc in taskcs:
            ids.append(tc.to_dict())
        return {"result": "success", "tasks": ids}


def version():
    filePath = os.path.join(path.GetTraderDir(), "VERSION")

    with open(filePath, "r", encoding="utf-8") as file:
        content = file.read()
        return content
