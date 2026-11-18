"""Compatibility surface for manual trade notifications and smoke helpers.

Domain values and rendering live in ``trader.core.notification``; delivery lives
in the email adapter.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from trader.core.notification.domain import ManualTradeAccountState, ManualTradeNotificationEvent
from trader.core.notification.rendering import (
    entry_or_exit_label,
    manual_trade_email_subject,
    operate_email_subject,
    render_manual_trade_email,
    render_operate_email,
)
from trader.core.shared.domain import Operate, OperateType
from trader.live.auto_execution import (
    AUTO_TRADE_MODE,
    MANUAL_NOTIFY_MODE,
    normalize_live_execution_mode,
)
from trader.notify.notify_type import parse_notice_config

__all__ = [
    "AUTO_TRADE_MODE",
    "MANUAL_NOTIFY_MODE",
    "AlwaysTriggerOneMinuteSmokeStrategy",
    "ManualNotifySmokeKline",
    "ManualTradeAccountState",
    "ManualTradeNotificationEvent",
    "build_manual_notify_smoke_event",
    "entry_or_exit_label",
    "manual_trade_email_subject",
    "normalize_live_execution_mode",
    "operate_email_subject",
    "render_manual_trade_email",
    "render_operate_email",
    "run_real_email_smoke",
]


@dataclass
class ManualNotifySmokeKline:
    open_time: int
    close: float


class AlwaysTriggerOneMinuteSmokeStrategy:
    name = "always_trigger_1m_smoke"

    def next_operation(self, kline: ManualNotifySmokeKline) -> Operate:
        return Operate(OperateType.BUY, int(kline.open_time), float(kline.close))


def build_manual_notify_smoke_event(kline: ManualNotifySmokeKline | None = None) -> ManualTradeNotificationEvent:
    if kline is None:
        kline = ManualNotifySmokeKline(open_time=int(time.time()), close=100.0)
    strategy = AlwaysTriggerOneMinuteSmokeStrategy()
    op = strategy.next_operation(kline)
    amount = 100.0
    quantity = amount / float(op.price)
    return ManualTradeNotificationEvent(
        market="SMOKEUSDT",
        strategy=strategy.name,
        task_id=0,
        mode=MANUAL_NOTIFY_MODE,
        action="ENTRY",
        side=op.otype.name,
        signal_time=int(op.dtime),
        signal_price=float(op.price),
        suggested_amount=amount,
        suggested_quantity=quantity,
        trigger_reason="signal_entry",
        local_state=ManualTradeAccountState(cash_before=amount, cash_after=0.0, position_before=0.0, position_after=quantity),
    )


def run_real_email_smoke(notice_config: str | None = None) -> dict:
    cfg = notice_config or os.environ.get("TRADER_MANUAL_NOTIFY_E2E_NOTICE")
    if not cfg:
        raise RuntimeError("missing TRADER_MANUAL_NOTIFY_E2E_NOTICE for real email smoke test")

    notices = parse_notice_config(cfg)
    if not notices:
        raise RuntimeError("TRADER_MANUAL_NOTIFY_E2E_NOTICE did not produce any usable mail notice")

    event = build_manual_notify_smoke_event()
    content = render_manual_trade_email(event)
    subject = "manual trade notification smoke"
    sent_recipients = []
    for notice in notices:
        err = notice.send(content, subject)
        if err is not None:
            raise RuntimeError(f"real email smoke send failed: {err}")
        sent_recipients.append(getattr(notice, "recipient", None))

    return {
        "sent": True,
        "recipient": ",".join([recipient for recipient in sent_recipients if recipient]),
        "subject": subject,
        "strategy": event.strategy,
        "signal_time": event.signal_time,
    }
