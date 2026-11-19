"""Async helpers shared by application use cases."""

import asyncio


async def sleep(log, seconds, msg=None):
    if msg:
        log.info(f"Waiting for {seconds} seconds for {msg}")
    await asyncio.sleep(seconds)
