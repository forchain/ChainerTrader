import time
from logging import Logger


class Context:
    running: bool = False

def sleep(log:Logger,seconds,msg=None):
    if msg:
        log.debug(f"Waiting for {seconds} seconds for {msg}")
    else:
        log.debug(f"Waiting for {seconds} seconds")
    time.sleep(seconds)