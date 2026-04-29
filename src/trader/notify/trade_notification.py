import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from trader.notify.notify_type import parse_notice_config
from trader.utils.operate import Operate, OperateType

MANUAL_NOTIFY_MODE = "manual_notify"
AUTO_TRADE_MODE = "auto_trade"


@dataclass
class ManualTradeAccountState:
    cash_before: float
    cash_after: float
    position_before: float
    position_after: float


@dataclass
class ManualTradeNotificationEvent:
    market: str
    strategy: str
    task_id: int
    mode: str
    action: str
    side: str
    signal_time: int
    signal_price: float
    suggested_amount: float
    suggested_quantity: float
    trigger_reason: str
    local_state: ManualTradeAccountState
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_reward_ratio: Optional[float] = None


@dataclass
class ManualNotifySmokeKline:
    open_time: int
    close: float


class AlwaysTriggerOneMinuteSmokeStrategy:
    name = "always_trigger_1m_smoke"

    def next_operation(self, kline: ManualNotifySmokeKline) -> Operate:
        return Operate(OperateType.BUY, int(kline.open_time), float(kline.close))


def normalize_live_execution_mode(value: str | None) -> str:
    mode = str(value or AUTO_TRADE_MODE).strip().lower()
    if mode in ("manual", "notify", MANUAL_NOTIFY_MODE):
        return MANUAL_NOTIFY_MODE
    return AUTO_TRADE_MODE


def entry_or_exit_label(action: str) -> str:
    return "进场" if str(action).upper() == "ENTRY" else "出场"


def render_manual_trade_email(event: ManualTradeNotificationEvent) -> str:
    signal_dt = datetime.fromtimestamp(int(event.signal_time)).strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "手动实盘通知",
        f"市场: {event.market}",
        f"策略: {event.strategy}",
        f"任务ID: {event.task_id}",
        f"模式: {event.mode}",
        f"操作: {entry_or_exit_label(event.action)}",
        f"方向: {event.side}",
        f"建议金额: {float(event.suggested_amount):.6f}",
        f"建议数量: {float(event.suggested_quantity):.8f}",
        f"信号价格: {float(event.signal_price):.6f}",
        f"信号时间: {signal_dt}",
        f"触发原因: {event.trigger_reason}",
        f"本地资金: {float(event.local_state.cash_before):.6f} -> {float(event.local_state.cash_after):.6f}",
        f"本地持仓: {float(event.local_state.position_before):.8f} -> {float(event.local_state.position_after):.8f}",
    ]
    if event.stop_loss is not None:
        lines.append(f"止损参考: {float(event.stop_loss):.6f}")
    if event.take_profit is not None:
        lines.append(f"止盈参考: {float(event.take_profit):.6f}")
    if event.risk_reward_ratio is not None:
        lines.append(f"风险收益比: {float(event.risk_reward_ratio):.6f}")
    lines.append("说明: 本邮件是 manual_notify 模式下的本地策略建议，不是交易所成交确认，也不表示系统已经提交任何交易所止损或止盈订单。")
    return "\n".join(lines)


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
