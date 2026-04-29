from trader.common.config import Config
from trader.common.log_tag import LogTag
from trader.common.logger import Logger
from trader.common.message import Message
from trader.notify.notify_type import parse_notice_config
from trader.notify.trade_notification import manual_trade_email_subject, operate_email_subject, render_manual_trade_email, render_operate_email


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
        for n in self.notice:
            content = render_operate_email(op)
            title = operate_email_subject(op)
            n.send(content, title)
            self.log.info(f"Notify {n.tp.name} : {op.to_dict()}")

    def send_manual_trade_notification(self, event) -> list[dict]:
        if self.notice is None or len(self.notice) <= 0:
            return []
        content = render_manual_trade_email(event)
        title = manual_trade_email_subject(event)
        sent = []
        for n in self.notice:
            err = n.send(content, title)
            info = {
                "notice_type": n.tp.name,
                "recipient": getattr(n, "recipient", None),
                "ok": err is None,
                "error": str(err) if err is not None else None,
            }
            sent.append(info)
            self.log.info(f"Notify {n.tp.name} : {event.to_dict()}")
        return sent
