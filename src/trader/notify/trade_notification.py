import html
import json
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
    interval: Optional[str] = None
    strategy_id: Optional[str] = None
    signal_event_id: Optional[str] = None
    breakeven_new_stop: Optional[float] = None
    breakeven_step: Optional[int] = None
    divergence_metadata: Optional[dict] = None

    def to_dict(self):
        return {
            "market": self.market,
            "interval": self.interval,
            "strategy": self.strategy,
            "strategy_id": self.strategy_id,
            "task_id": self.task_id,
            "mode": self.mode,
            "action": self.action,
            "side": self.side,
            "signal_time": self.signal_time,
            "signal_price": self.signal_price,
            "suggested_amount": self.suggested_amount,
            "suggested_quantity": self.suggested_quantity,
            "trigger_reason": self.trigger_reason,
            "local_state": self.local_state.__dict__,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_reward_ratio": self.risk_reward_ratio,
            "signal_event_id": self.signal_event_id,
            "breakeven_new_stop": self.breakeven_new_stop,
            "breakeven_step": self.breakeven_step,
            "divergence_metadata": self.divergence_metadata,
        }


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


def _fmt_number(value, precision: int = 6) -> str:
    if value is None:
        return "-"
    return f"{float(value):.{precision}f}"


def _fmt_time(value: int | float | None) -> str:
    if value is None:
        return "-"
    return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")


def _cell(value) -> str:
    if value is None:
        return "-"
    return html.escape(str(value))


def _row(label: str, value, accent: bool = False) -> str:
    cls = " class=\"accent\"" if accent else ""
    return f"<tr><th>{html.escape(label)}</th><td{cls}>{_cell(value)}</td></tr>"


def _section(title: str, rows: list[str]) -> str:
    if not rows:
        return ""
    return f"""
      <section class="panel">
        <h2>{html.escape(title)}</h2>
        <table>{''.join(rows)}</table>
      </section>
    """


def _metadata_rows(metadata: dict | None) -> list[str]:
    if not isinstance(metadata, dict) or not metadata:
        return []
    rows = []
    for key in sorted(metadata.keys()):
        value = metadata[key]
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        rows.append(_row(str(key), value))
    return rows


def manual_trade_email_subject(event: ManualTradeNotificationEvent) -> str:
    interval = f" {event.interval}" if event.interval else ""
    return f"[手动实盘] {event.market}{interval} {entry_or_exit_label(event.action)} {event.side} @ {_fmt_number(event.signal_price)}"


def render_manual_trade_email(event: ManualTradeNotificationEvent) -> str:
    action_label = entry_or_exit_label(event.action)
    risk_rows = []
    if event.stop_loss is not None:
        risk_rows.append(_row("止损参考", _fmt_number(event.stop_loss), accent=True))
    if event.take_profit is not None:
        risk_rows.append(_row("止盈参考", _fmt_number(event.take_profit), accent=True))
    if event.risk_reward_ratio is not None:
        risk_rows.append(_row("风险收益比", _fmt_number(event.risk_reward_ratio)))
    if event.breakeven_new_stop is not None:
        risk_rows.append(_row("保本止损参考", _fmt_number(event.breakeven_new_stop), accent=True))
    if event.breakeven_step is not None:
        risk_rows.append(_row("保本触发 step", event.breakeven_step))

    diagnostic_rows = [
        _row("策略", event.strategy),
        _row("策略ID", event.strategy_id),
        _row("任务ID", event.task_id),
        _row("模式", event.mode),
        _row("触发原因", event.trigger_reason),
        _row("图表事件ID", event.signal_event_id),
    ]
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <style>
      body {{ margin:0; padding:0; background:#f4f6f8; color:#17202a; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
      .wrap {{ max-width:760px; margin:0 auto; padding:24px; }}
      .hero {{ background:#101820; color:#fff; border-radius:10px; padding:22px 24px; }}
      .eyebrow {{ color:#9fb4c7; font-size:13px; letter-spacing:.04em; text-transform:uppercase; }}
      .title {{ margin:8px 0 12px; font-size:24px; font-weight:700; }}
      .badge {{
        display:inline-block; border-radius:999px; padding:5px 11px; margin-right:8px;
        background:#1f8f5f; color:#fff; font-weight:700; font-size:13px;
      }}
      .badge.exit {{ background:#b54708; }}
      .price {{ font-size:30px; font-weight:750; margin-top:12px; }}
      .sub {{ color:#c8d2dc; margin-top:6px; }}
      .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:16px; }}
      .panel {{ background:#fff; border:1px solid #d9e1e8; border-radius:8px; padding:16px; margin-top:14px; }}
      h2 {{ margin:0 0 10px; font-size:16px; }}
      table {{ width:100%; border-collapse:collapse; }}
      th {{ width:38%; text-align:left; color:#667085; font-weight:600; padding:8px 6px 8px 0; border-top:1px solid #eef2f5; vertical-align:top; }}
      td {{ padding:8px 0; border-top:1px solid #eef2f5; word-break:break-word; }}
      td.accent {{ font-weight:750; color:#101820; }}
      .warning {{
        background:#fff7ed; border:1px solid #fed7aa; color:#7c2d12; border-radius:8px;
        padding:12px 14px; margin-top:14px; line-height:1.5;
      }}
      @media (max-width:680px) {{ .grid {{ grid-template-columns:1fr; }} .wrap {{ padding:14px; }} }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="hero">
        <div class="eyebrow">手动实盘操作建议</div>
        <div class="title">{_cell(event.market)} {_cell(event.interval or "")}</div>
        <span class="badge {'exit' if str(event.action).upper() == 'EXIT' else ''}">{_cell(action_label)}</span>
        <span class="badge">{_cell(event.side)}</span>
        <div class="price">@ {_cell(_fmt_number(event.signal_price))}</div>
        <div class="sub">信号时间: {_cell(_fmt_time(event.signal_time))}</div>
      </div>

      <div class="grid">
        {_section("操作建议", [
            _row("操作", action_label, accent=True),
            _row("方向", event.side, accent=True),
            _row("建议金额", _fmt_number(event.suggested_amount), accent=True),
            _row("建议数量", _fmt_number(event.suggested_quantity, 8), accent=True),
            _row("信号价格", _fmt_number(event.signal_price), accent=True),
        ])}
        {_section("本地账户变化", [
            _row("本地资金", f"{_fmt_number(event.local_state.cash_before)} -> {_fmt_number(event.local_state.cash_after)}"),
            _row("本地持仓", f"{_fmt_number(event.local_state.position_before, 8)} -> {_fmt_number(event.local_state.position_after, 8)}"),
        ])}
      </div>

      {_section("风险参考", risk_rows)}
      {_section("诊断信息", diagnostic_rows)}
      {_section("背离/信号元数据", _metadata_rows(event.divergence_metadata))}

      <div class="warning">
        说明: 本邮件是 manual_notify 模式下的本地策略建议，不是交易所成交确认，也不表示系统已经提交任何交易所止损或止盈订单。
        操作前请核对交易所盘口、持仓、可用余额、图表信号和风险位。
      </div>
    </div>
  </body>
</html>"""


def operate_email_subject(op: Operate) -> str:
    return f"[策略信号] {op.otype.name if op.otype else 'UNKNOWN'} @ {_fmt_number(op.price)}"


def render_operate_email(op: Operate) -> str:
    op_type = op.otype.name if op.otype else "UNKNOWN"
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <style>
      body {{ margin:0; padding:0; background:#f4f6f8; color:#17202a; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
      .wrap {{ max-width:640px; margin:0 auto; padding:24px; }}
      .card {{ background:#fff; border:1px solid #d9e1e8; border-radius:10px; overflow:hidden; }}
      .head {{ background:#101820; color:#fff; padding:20px 22px; }}
      .title {{ margin:0; font-size:22px; }}
      .body {{ padding:18px 22px; }}
      table {{ width:100%; border-collapse:collapse; }}
      th {{ width:34%; text-align:left; color:#667085; font-weight:600; padding:10px 6px 10px 0; border-top:1px solid #eef2f5; }}
      td {{ padding:10px 0; border-top:1px solid #eef2f5; font-weight:700; }}
      .warning {{
        background:#fff7ed; border:1px solid #fed7aa; color:#7c2d12; border-radius:8px;
        padding:12px 14px; margin-top:14px; line-height:1.5;
      }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <div class="head"><h1 class="title">策略信号提醒</h1></div>
        <div class="body">
          <table>
            {_row("信号类型", op_type, accent=True)}
            {_row("信号价格", _fmt_number(op.price), accent=True)}
            {_row("信号时间", _fmt_time(op.dtime))}
          </table>
          <div class="warning">
            这是策略操作信号的基础通知。若当前任务为 manual_notify 模式且没有生成手动操作事件，系统不会把它当作已成交或已下单。
          </div>
        </div>
      </div>
    </div>
  </body>
</html>"""



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
