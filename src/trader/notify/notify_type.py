import json
import os
import smtplib
from email.mime.text import MIMEText
from enum import Enum

from trader.common import path


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


class NotifyMail:
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
        self.sender = sender
        self.password = password
        self.recipients = normalize_recipients(recipients if recipients is not None else recipient)
        self.recipient = ",".join(self.recipients)

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

    def send(self, content: str, title: str = "Trader"):
        subtype = "html" if is_html_content(content) else "plain"
        msg = MIMEText(content, subtype, "utf-8")
        msg["Subject"] = title
        msg["From"] = self.sender
        msg["To"] = self.recipient

        try:
            server = smtplib.SMTP_SSL(self.stmp_server, self.stmp_port)
            # if self.tp == NotifyType.MAIL_GMAIL:
            # server.starttls()

            server.login(self.sender, self.password)
            server.sendmail(self.sender, self.recipients, msg.as_string())
            server.quit()
            return None
        except Exception as e:
            return e


def normalize_recipients(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.replace(";", ",").split(",")
    elif isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.extend(item.replace(";", ",").split(","))
    else:
        parts = []
    return [part.strip() for part in parts if part and part.strip()]


def is_html_content(content: str) -> bool:
    stripped = str(content or "").lstrip().lower()
    return stripped.startswith("<!doctype html") or stripped.startswith("<html")


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

    ret = []
    mail_template = default_notify_mail_template()

    for nc in parsed_list:
        ntype = parse_notify_type(nc["type"])
        if ntype is not None and ntype.is_mail():
            password = nc["password"]
            if password == "your_smtp_auth_code":
                continue
            sender = nc["sender"]
            recipient = nc.get("recipients", nc.get("recipient", sender))
            tm = mail_template[ntype]
            nm = NotifyMail(tm.tp, tm.stmp_server, tm.stmp_port, sender, password, recipient)
            ret.append(nm)
    return ret
