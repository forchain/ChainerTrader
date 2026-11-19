"""Notice configuration for the email adapter."""

from __future__ import annotations

import json
import os
from enum import Enum

from trader.adapters.outbound.email.sender import EmailNotificationSender
from trader.core.notification.domain import Notice
from trader.core.notification.use_cases import normalize_recipients, notices_from_entries
from trader.core.shared import paths as path


class NotifyType(Enum):
    UNKNOWN = 0
    MAIL_QQ = 1
    MAIL_GMAIL = 2
    MAIL_OUTLOOK = 3
    MAIL_163 = 4
    MAIL_LARK = 5

    def is_mail(self):
        return (
            self == NotifyType.MAIL_QQ
            or self == NotifyType.MAIL_GMAIL
            or self == NotifyType.MAIL_OUTLOOK
            or self == NotifyType.MAIL_163
            or self == NotifyType.MAIL_LARK
        )


def parse_notify_type(name):
    if name == NotifyType.UNKNOWN.name:
        return NotifyType.UNKNOWN
    elif name == NotifyType.MAIL_QQ.name:
        return NotifyType.MAIL_QQ
    elif name == NotifyType.MAIL_GMAIL.name:
        return NotifyType.MAIL_GMAIL
    elif name == NotifyType.MAIL_OUTLOOK.name:
        return NotifyType.MAIL_OUTLOOK
    elif name == NotifyType.MAIL_163.name:
        return NotifyType.MAIL_163
    elif name == NotifyType.MAIL_LARK.name:
        return NotifyType.MAIL_LARK
    return None


class NotifyMail(EmailNotificationSender):
    def __init__(
        self,
        tp: NotifyType,
        stmp_server: str,
        stmp_port: int,
        sender: str = None,
        password: str = None,
        recipient: str = None,
        recipients: list[str] | None = None,
    ):
        self.tp = tp
        self.stmp_server = stmp_server
        self.stmp_port = stmp_port
        normalized = normalize_recipients(recipients if recipients is not None else recipient)
        super().__init__(Notice(tp.name, stmp_server, stmp_port, sender=sender, password=password, recipients=tuple(normalized)))

    @classmethod
    def from_notice(cls, notice: Notice) -> "NotifyMail":
        return cls(
            NotifyType[notice.notice_type],
            notice.server,
            notice.port,
            sender=notice.sender,
            password=notice.password,
            recipients=list(notice.recipients),
        )

    @property
    def sender(self) -> str | None:
        return self.notice.sender

    @property
    def password(self) -> str | None:
        return self.notice.password

    @property
    def recipients(self) -> list[str]:
        return list(self.notice.recipients)

    def to_dict(self):
        return {
            "type": self.tp.name,
            "stmp_server": self.stmp_server,
            "stmp_port": self.stmp_port,
            "sender": self.sender,
            "password": self.password,
            "recipient": self.recipient,
            "recipients": self.recipients,
        }


def default_notify_mail_template():
    ret = {}
    ret[NotifyType.MAIL_QQ] = NotifyMail(NotifyType.MAIL_QQ, "smtp.qq.com", 465)
    ret[NotifyType.MAIL_GMAIL] = NotifyMail(NotifyType.MAIL_GMAIL, "smtp.gmail.com", 465)
    ret[NotifyType.MAIL_OUTLOOK] = NotifyMail(NotifyType.MAIL_OUTLOOK, "smtp.office365.com", 465)
    ret[NotifyType.MAIL_163] = NotifyMail(NotifyType.MAIL_163, "smtp.163.com", 465)
    ret[NotifyType.MAIL_LARK] = NotifyMail(NotifyType.MAIL_LARK, "smtp.larksuite.com", 465)

    return ret


def parse_notice_config(cfg):
    file_path = path.get_file_path(cfg)
    if os.path.isfile(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                parsed_list = json.load(file)
        except json.JSONDecodeError:
            return []
        except FileNotFoundError:
            return []
    elif path.is_like_file(cfg):
        raise FileNotFoundError(f"notice config file not found: {file_path}")
    else:
        parsed_list = json.loads(cfg)

    return [NotifyMail.from_notice(notice) for notice in notices_from_entries(parsed_list)]
