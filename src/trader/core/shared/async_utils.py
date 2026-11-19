"""Async helpers shared by application use cases."""

import asyncio
from asyncio import Event


async def sleep(log, seconds, msg=None):
    if msg:
        log.info(f"Waiting for {seconds} seconds for {msg}")
    await asyncio.sleep(seconds)


async def sleep_loop(log, seconds, quit: Event, msg=None):
    if msg:
        log.info(f"Waiting for {seconds} seconds for {msg}")
    else:
        log.info(f"Waiting for {seconds} seconds")

    cur = seconds
    while cur > 0 and (not quit.is_set()):
        await asyncio.sleep(1)
        cur -= 1
