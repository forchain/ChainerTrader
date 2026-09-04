import asyncio
import importlib
from asyncio import Event
from datetime import datetime
from logging import Logger

NAME = "trader"


async def sleep(log: Logger, seconds, msg=None):
    if msg:
        log.info(f"Waiting for {seconds} seconds for {msg}")
    await asyncio.sleep(seconds)


async def sleep_loop(log: Logger, seconds, quit: Event, msg=None):
    if msg:
        log.info(f"Waiting for {seconds} seconds for {msg}")
    else:
        log.info(f"Waiting for {seconds} seconds")

    cur = seconds
    while cur > 0 and (not quit.is_set()):
        await asyncio.sleep(1)
        cur -= 1


def parse_datetime(str) -> datetime:
    if str.isdigit():
        return datetime.fromtimestamp(int(str))
    else:
        return datetime.strptime(str, "%Y-%m-%d %H:%M:%S")


def dynamic_load_create(module_name, class_name, *args, **kwargs):
    try:
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
        instance = cls(*args, **kwargs)
        return instance
    except (ModuleNotFoundError, AttributeError) as e:
        print(f"Error: {e}")
        return None


def dynamic_load(module_name, class_name):
    try:
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
        return cls
    except (ModuleNotFoundError, AttributeError) as e:
        print(f"Error: {e}")
        return None


MIN_RECORDS_NUM = 100
