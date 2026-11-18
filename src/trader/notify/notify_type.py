"""Compatibility import surface for the email notification adapter."""

from trader.adapters.outbound.email.config import (
    NotifyMail,
    NotifyType,
    default_notify_mail_template,
    parse_notice_config,
    parse_notify_type,
)
from trader.adapters.outbound.email.sender import is_html_content
from trader.core.notification.use_cases import normalize_recipients

__all__ = [
    "NotifyMail",
    "NotifyType",
    "default_notify_mail_template",
    "is_html_content",
    "normalize_recipients",
    "parse_notice_config",
    "parse_notify_type",
]
