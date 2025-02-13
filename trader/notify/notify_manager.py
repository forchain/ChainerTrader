
from trader.common.config import Config
from trader.common.logger import Logger
from trader.common.message import Message
from trader.notify.notify_type import parse_notice_config


class NotifyManager:
    def __init__(self,cfg:Config,log:Logger):
        self.log = log.log()
        self.cfg = cfg
        self.log.info(f"Init NotifyManager")
        self.notice=None

    def start(self):
        self.load_config()

    def load_config(self):
        if self.cfg.notice is None:
            return
        self.notice=parse_notice_config(self.cfg.notice)
        if self.notice is None or len(self.notice) <= 0:
            return
        for n in self.notice:
            self.log.info(f"Load notice:{n.to_dict()}")


    def handler(self, msg: Message):
        if self.notice is None or len(self.notice) <= 0:
            return
        if msg.data is None or msg.data.tret.operate is None:
            return
        for n in self.notice:
            content=f"{msg.data.tret.operate.to_dict()}"
            n.send(content,"trader operate")
            self.log.info(f"Notify {n.tp.name} : {content}")