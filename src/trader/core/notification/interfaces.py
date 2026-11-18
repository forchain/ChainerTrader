"""Outbound port for notification delivery."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class NotificationSender(Protocol):
    """Deliver already-rendered content to one configured notice target."""

    notice_type: str
    recipient: str | None

    def send(self, content: str, title: str = "Trader") -> Exception | None: ...
