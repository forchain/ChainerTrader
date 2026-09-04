import asyncio
import time
from logging import Logger

NAME = "trader"

class Context:
    running: bool = False

async def sleep(log:Logger,seconds,msg=None):
    if msg:
        log.info(f"Waiting for {seconds} seconds for {msg}")
    else:
        log.info(f"Waiting for {seconds} seconds")
    await asyncio.sleep(seconds)