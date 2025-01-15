import asyncio
import time
from datetime import datetime
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

def parse_datetime(str)->datetime:
    if str.isdigit():
        return datetime.fromtimestamp(int(str))
    else:
        return datetime.strptime(str, "%Y-%m-%d %H:%M:%S")
