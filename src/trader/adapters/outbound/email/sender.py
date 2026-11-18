"""SMTP-backed notification sender adapter."""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from typing import Protocol

from trader.core.notification.domain import Notice


class EmailTransport(Protocol):
    def send(self, notice: Notice, message: str) -> None: ...


class SmtpSslTransport:
    """Default transport; resolved at call time so tests can inject or patch it."""

    def send(self, notice: Notice, message: str) -> None:
        server = smtplib.SMTP_SSL(notice.server, notice.port)
        try:
            server.login(notice.sender, notice.password)
            server.sendmail(notice.sender, list(notice.recipients), message)
        finally:
            server.quit()


def is_html_content(content: str) -> bool:
    stripped = str(content or "").lstrip().lower()
    return stripped.startswith("<!doctype html") or stripped.startswith("<html")


class EmailNotificationSender:
    """Deliver rendered notification content over SMTP.

    Implements the notification sender port. A transport can be injected so the
    adapter is exercised without a real SMTP server.
    """

    def __init__(self, notice: Notice, transport: EmailTransport | None = None):
        self.notice = notice
        self.transport = transport if transport is not None else SmtpSslTransport()

    @property
    def notice_type(self) -> str:
        return self.notice.notice_type

    @property
    def recipient(self) -> str:
        return self.notice.recipient

    def send(self, content: str, title: str = "Trader") -> Exception | None:
        subtype = "html" if is_html_content(content) else "plain"
        msg = MIMEText(content, subtype, "utf-8")
        msg["Subject"] = title
        msg["From"] = self.notice.sender
        msg["To"] = self.notice.recipient

        try:
            self.transport.send(self.notice, msg.as_string())
            return None
        except Exception as e:
            return e
