"""Notification use cases: notice configuration and notification delivery."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from trader.core.notification.domain import ManualTradeNotificationEvent, Notice
from trader.core.notification.interfaces import NotificationSender
from trader.core.notification.rendering import (
    manual_trade_email_subject,
    operate_email_subject,
    render_manual_trade_email,
    render_operate_email,
)
from trader.core.shared.domain import Operate

DEFAULT_MAIL_SERVERS: dict[str, tuple[str, int]] = {
    "MAIL_QQ": ("smtp.qq.com", 465),
    "MAIL_GMAIL": ("smtp.gmail.com", 465),
    "MAIL_OUTLOOK": ("smtp.office365.com", 465),
    "MAIL_163": ("smtp.163.com", 465),
    "MAIL_LARK": ("smtp.larksuite.com", 465),
}

PLACEHOLDER_PASSWORD = "your_smtp_auth_code"


@dataclass(frozen=True)
class DeliveryResult:
    notice_type: str
    recipient: str | None
    ok: bool
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "notice_type": self.notice_type,
            "recipient": self.recipient,
            "ok": self.ok,
            "error": self.error,
        }


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


def notice_from_entry(entry: Mapping[str, Any], servers: Mapping[str, tuple[str, int]] = DEFAULT_MAIL_SERVERS) -> Notice | None:
    notice_type = entry["type"]
    server = servers.get(notice_type)
    if server is None:
        return None
    password = entry["password"]
    if password == PLACEHOLDER_PASSWORD:
        return None
    sender = entry["sender"]
    recipients = normalize_recipients(entry.get("recipients", entry.get("recipient", sender)))
    return Notice(
        notice_type=notice_type,
        server=server[0],
        port=server[1],
        sender=sender,
        password=password,
        recipients=tuple(recipients),
    )


def notices_from_entries(entries: Iterable[Mapping[str, Any]], servers: Mapping[str, tuple[str, int]] = DEFAULT_MAIL_SERVERS) -> list[Notice]:
    notices = []
    for entry in entries:
        notice = notice_from_entry(entry, servers)
        if notice is not None:
            notices.append(notice)
    return notices


def _deliver(senders: Iterable[NotificationSender], subject: str, content: str) -> list[DeliveryResult]:
    results = []
    for sender in senders:
        error = sender.send(content, subject)
        results.append(
            DeliveryResult(
                notice_type=sender.notice_type,
                recipient=sender.recipient,
                ok=error is None,
                error=str(error) if error is not None else None,
            )
        )
    return results


class SendManualTradeNotification:
    def __init__(self, senders: Iterable[NotificationSender]):
        self.senders = list(senders)

    def execute(self, event: ManualTradeNotificationEvent) -> list[DeliveryResult]:
        return _deliver(self.senders, manual_trade_email_subject(event), render_manual_trade_email(event))


class SendOperateNotification:
    def __init__(self, senders: Iterable[NotificationSender]):
        self.senders = list(senders)

    def execute(self, op: Operate) -> list[DeliveryResult]:
        return _deliver(self.senders, operate_email_subject(op), render_operate_email(op))
