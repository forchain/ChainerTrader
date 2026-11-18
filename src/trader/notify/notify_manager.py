from trader.common.config import Config
from trader.common.log_tag import LogTag
from trader.common.logger import Logger
from trader.common.message import Message
from trader.core.notification.use_cases import SendManualTradeNotification, SendOperateNotification
from trader.notify.notify_type import parse_notice_config


class NotifyManager:
    def __init__(self, cfg: Config, log: Logger):
        self.log = log
        self.cfg = cfg
        self.log.info("Init NotifyManager")
        self.notice = None

    def start(self):
        self.load_config()

    def load_config(self):
        if self.cfg.notice is None:
            return
        self.notice = parse_notice_config(self.cfg.notice)
        if self.notice is None or len(self.notice) <= 0:
            return
        for n in self.notice:
            self.log.info(f"Load notice:{n.to_dict()}", LogTag.PRIVATE)

    def handler(self, msg: Message):
        if self.notice is None or len(self.notice) <= 0:
            return
        if msg.data is None:
            return
        manual_events = getattr(msg.data, "manual_trade_notifications", None)
        if manual_events is not None:
            for event in manual_events:
                self.send_manual_trade_notification(event)
            return

        tret = getattr(msg.data, "tret", None)
        opts = getattr(tret, "opts", None)
        if not opts:
            ts = getattr(msg.data, "ts", None)
            tret = getattr(ts, "tret", None)
            opts = getattr(tret, "opts", None)
        if not opts:
            return
        op = opts[-1]
        if not hasattr(op, "to_dict"):
            return
        for result in SendOperateNotification(self.notice).execute(op):
            self.log.info(f"Notify {result.notice_type} : {op.to_dict()}")

    def send_manual_trade_notification(self, event) -> list[dict]:
        if self.notice is None or len(self.notice) <= 0:
            return []
        results = SendManualTradeNotification(self.notice).execute(event)
        for result in results:
            self.log.info(f"Notify {result.notice_type} : {event.to_dict()}")
        return [result.to_dict() for result in results]
