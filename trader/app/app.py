import asyncio
import os
import signal
from datetime import datetime
from math import trunc

from trader.app.database_manager import DatabaseManager
from trader.common.message import Message, new_exit_msg, new_str_msg
from trader.task.task_manager import TaskManager
from trader.binance.exchange import EXCHANGE_NAME, BinanceExchange
from trader.common.common import Context, sleep, NAME
from trader.common.config import Config, default
from trader.common.logger import Logger
from trader.common import path


class App:
    def __init__(self,cfg:Config=default()):
        self.cfg = cfg
        self.logger=Logger(cfg)

        self.log().info(f"Init App {self.name()}")

        self.db_manager=None
        self.exchange=None

        if self.cfg.db_uri:
            self.db_manager = DatabaseManager(cfg, self.logger)
        if self.cfg.exchange == EXCHANGE_NAME:
            self.exchange = BinanceExchange(self.cfg, self.log())

        self.task_manager=None
        if self.cfg.tasks:
            self.task_manager = TaskManager(self.cfg, self.log(), self.db_manager, self.exchange)

        self.startTime = datetime.now()

    def name(self):
        return NAME

    def log(self):
        return self.logger.log()

    def start(self):
        if self.cfg.tasks is None:
            self.log().warn(f"No tasks can be executed")
            return True

        self.log().info(f"Start {self.name()} App, config:{self.cfg.to_dict()}")

        if self.db_manager:
            self.db_manager.start()
        if  self.exchange:
            self.exchange.start()

        self.process()

        return True

    def stop(self):
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
            "name":self.name(),
            "version":self.version(),
            "commission": self.cfg.commission,
            "period": self.cfg.period,
            "atr": self.cfg.atr,
        }

    def config(self):
        return self.cfg

    def process(self):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.shutdown, loop)

        try:
            loop.run_until_complete(self.start_handler())
        except asyncio.CancelledError:
            self.log().debug("All events have been cancelled.")
        finally:
            loop.close()
            self.log().info(f"{self.name()} events exited.")

    def shutdown(self,loop):
        self.log().info(f"Received shutdown signal, stopping {self.name()}...")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    async def start_handler(self):
        queue = asyncio.Queue()

        managers=[]
        if self.task_manager:
            managers.append(asyncio.create_task(self.task_manager.start(queue)))
        handlers = asyncio.create_task(self.handler(queue))

        await asyncio.gather(*managers)
        await handlers

    async def handler(self,queue):
        self.log().info(f"{self.name()} enter listen_to_queue")

        while True:
            msg:Message = await queue.get()
            self.log().debug(f"Processing message: {msg.name()}")
            if msg.is_exit():
                self.log().info("Received exit message, shutting down...")
                break
            if msg.is_task():
                self.task_manager.handler(msg)

            queue.task_done()

        self.log().info(f"{self.name()} exit listen_to_queue")

def version():
    filePath = os.path.join(path.GetTraderDir(), 'VERSION')

    with open(filePath, "r", encoding="utf-8") as file:
        content = file.read()
        return content