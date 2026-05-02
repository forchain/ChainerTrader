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
        self.main_task_error = None
        self.handler_ready = None

    def process(self, msgs: list[Message]):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        self.quit = asyncio.Event()
        self.handler_ready = asyncio.Event()
        self.main_task = loop.create_task(self.main_task_handler(msgs, self.quit))
        self.main_task.add_done_callback(self._on_main_task_done)
        self.logger.info("Create main task for RPC App")

    def _mark_handler_ready(self):
        if self.handler_ready:
            self.handler_ready.set()

    def _on_main_task_done(self, task: asyncio.Task):
        if task.cancelled():
            return
        try:
            task.result()
        except Exception as exc:
            self.main_task_error = exc
            self.log().exception("RPC App main task failed")

    def raise_main_task_error(self):
        if self.main_task_error:
            raise self.main_task_error
        if self.main_task and self.main_task.done():
            self.main_task.result()

    async def wait_until_handler_ready(self):
        if not self.main_task or not self.handler_ready:
            return

        ready_task = asyncio.create_task(self.handler_ready.wait())
        done, pending = await asyncio.wait(
            {ready_task, self.main_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if ready_task in pending:
            ready_task.cancel()

        if self.main_task in done:
            self.raise_main_task_error()

    async def main_task_handler(self, msgs: list[Message], quit: Event):
        self.logger.info("Enter main_task_handler")
        await self.handler(msgs, quit)
        await sleep(self.logger, 1, "Try to exit rpc...")
        # exit uvicorn
        # os.kill(os.getpid(), signal.SIGTERM)
        os.kill(os.getpid(), signal.SIGINT)
        self.logger.info("Exit main_task_handler")

    async def stop(self):
        if self.main_task and not self.main_task.done():
            self.log().info("Retry quit main task")
            self.exit_handle(self.quit)
            await self.main_task

        self.logger.info("Stop RPC App")
