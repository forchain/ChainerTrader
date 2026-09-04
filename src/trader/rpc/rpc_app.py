import asyncio
import os
import signal
from asyncio import Event

from trader.app.app import App
from trader.common.common import sleep
from trader.common.config import Config
from trader.common.message import Message


class RpcApp(App):

    def __init__(self, cfg: Config):
        super().__init__(cfg)
        self.main_task = None
        self.quit = None

    def process(self, msgs: list[Message]):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        self.quit = asyncio.Event()
        self.main_task = loop.create_task(self.main_task_handler(msgs, self.quit))
        self.log().info("Create main task for RPC App")

    async def main_task_handler(self, msgs: list[Message], quit: Event):
        self.log().info("Enter main_task_handler")
        await self.handler(msgs, quit)
        await sleep(self.log(), 1, "Try to exit rpc...")
        # exit uvicorn
        # os.kill(os.getpid(), signal.SIGTERM)
        os.kill(os.getpid(), signal.SIGINT)
        self.log().info("Exit main_task_handler")

    async def stop(self):
        if self.main_task and not self.main_task.done():
            self.log().info("Retry quit main task")
            self.exit_handle(self.quit)
            await self.main_task

        self.log().info("Stop RPC App")
