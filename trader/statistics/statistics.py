from logging import Logger

from trader.common.message import Message


class Statistics:
    def __init__(self,cfg,log:Logger):
        self.log = log
        self.cfg = cfg
        self.log.info(f"Init Statistics")

    def handler(self,msg:Message):
        self.log.info(f"handle message:{msg.name()}")