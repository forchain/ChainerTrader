import os
import signal

from trader.app.app import App
from trader.common.config import Config
import asyncio
from asyncio import Event, Queue

class RpcApp(App):

    def __init__(self,cfg:Config):
        super().__init__(cfg)
        self.main_task=None
        self.quit=None

    def process(self):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        self.quit = asyncio.Event()
        self.main_task = loop.create_task(self.main_task_handler(self.quit))
        self.log().info(f"Create main task for RPC App")

    async def main_task_handler(self,quit:Event):
        self.log().info(f"Enter main_task_handler")
        await self.start_handler(self.quit)

        # exit uvicorn
        #os.kill(os.getpid(), signal.SIGTERM)
        os.kill(os.getpid(), signal.SIGINT)
        self.log().info(f"Exit main_task_handler")


    async def stop(self):
        if not self.main_task.done():
            self.log().info(f"Retry quit main task")
            self.quit.set()
            await self.main_task

        self.log().info(f"Stop RPC App")