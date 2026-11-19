"""Pure rendering rules for notification payloads.

These functions build subjects and HTML bodies only. Delivery is an outbound
adapter concern, so rendering can be tested without SMTP or a network.
"""

from __future__ import annotations

import html
import json
from datetime import datetime

from trader.core.notification.domain import ManualTradeNotificationEvent
from trader.core.shared.domain import Operate


def entry_or_exit_label(action: str) -> str:
    normalized = str(action).upper()
    if normalized == "ENTRY":
        return "进场"
    if normalized == "EXIT":
        return "出场"
    if normalized == "RISK_UPDATE":
        return "风险更新"
    return normalized


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


def _row(label: str, value, accent: bool = False, raw: bool = False) -> str:
    cls = " class=\"accent\"" if accent else ""
    rendered_value = str(value) if raw else _cell(value)
    return f"<tr><th>{html.escape(label)}</th><td{cls}>{rendered_value}</td></tr>"


def _json_details(label: str, value) -> str:
    formatted = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    return f"""
      <details class="json-details">
        <summary>{html.escape(label)}</summary>
        <pre class="json-block">{html.escape(formatted)}</pre>
      </details>
    """


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
            rows.append(_row(str(key), _json_details(str(key), value), raw=True))
        else:
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
      .json-details summary {{ cursor:pointer; color:#344054; font-weight:700; }}
      .json-block {{
        margin:8px 0 0; padding:10px; border-radius:6px; background:#f8fafc; color:#111827;
        white-space:pre-wrap; word-break:break-word; font-size:12px; line-height:1.45;
      }}
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
