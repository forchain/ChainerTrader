from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

ORDER_ROLE_KEY = "chainer_role"
ORDER_ROLE_ENTRY = "entry"
ORDER_ROLE_EXIT = "exit"
ORDER_ROLE_STOP = "stop"
ORDER_ROLE_TP = "take_profit"


class TradeStatus(str, Enum):
    PENDING_ENTRY_CONFIRM = "pending_entry_confirm"
    OPENING = "opening"
    ACTIVE = "active"
    PENDING_EXIT_CONFIRM = "pending_exit_confirm"
    CLOSING = "closing"
    CLOSED = "closed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class KlineRef:
    dt: datetime
    high: float
    low: float


@dataclass
class TradeContext:
    trade_id: int
    key: str
    direction: str
    order: Any
    entry_key_bar_index: int
    key_kline_ref: KlineRef
    stoploss_atr_mult: float

    status: TradeStatus
    entry_need_confirm: bool
    exit_need_confirm: bool
    enable_breakeven: bool
    risk_reward_ratio: float

    entry_price: float | None = None
    exit_price: float | None = None
    exit_value: float | None = None
    tp_price: float | None = None
    signal_metadata: dict[str, Any] | None = None

    initial_stop_price: float | None = None
    stop_price: float | None = None
    breakeven_step: int = 0

    entry_key_banned: bool = False
    exit_key_banned: bool = False
    exit_key_bar_index: int | None = None
    exit_key_kline_ref: KlineRef | None = None

    cancel_reason: str | None = None
    stop_order: Any = None
    tp_order: Any = None
    pending_exit_reason: dict[str, Any] | None = None
    requested_exit_reason_code: str | None = None
    requested_exit_reason_label: str | None = None
    requested_exit_reason_detail: str | None = None
    exit_reason_code: str | None = None
    exit_reason_label: str | None = None
    exit_reason_detail: str | None = None
    stop_multiple_r: float | None = None
    exit_risk_reward_ratio: float | None = None


@dataclass
class SignalSnapshot:
    bar_index: int
    long_signal: bool
    short_signal: bool
    long_context: dict[str, Any] = field(default_factory=dict)
    short_context: dict[str, Any] = field(default_factory=dict)


class TradeRegistry:
    def __init__(self) -> None:
        self.trade_seq = 0
        self.active_trade: TradeContext | None = None
        self.trades_by_id: dict[int, TradeContext] = {}
        self.trades_by_key: dict[str, TradeContext] = {}
        self.banned_entry_key_bar_index: set[int] = set()
        self.banned_exit_key_bar_index: set[int] = set()

    def allocate_trade_id(self) -> int:
        self.trade_seq += 1
        return self.trade_seq

    def register(self, ctx: TradeContext) -> None:
        self.trades_by_id[ctx.trade_id] = ctx
        self.trades_by_key[ctx.key] = ctx

    def resolve(self, trade_ref: int | str | None) -> TradeContext | None:
        if trade_ref is None:
            return self.active_trade
        if isinstance(trade_ref, int):
            return self.trades_by_id.get(int(trade_ref))
        ref_str = str(trade_ref)
        if ref_str.isdigit():
            return self.trades_by_id.get(int(ref_str))
        return self.trades_by_key.get(ref_str)

    def has_open_trade(self) -> bool:
        return self.active_trade is not None and self.active_trade.status not in {
            TradeStatus.CLOSED,
            TradeStatus.CANCELLED,
        }

    def no_active_trade(self) -> bool:
        return not self.has_open_trade()

    def clear_active_if_matches(self, ctx: TradeContext) -> None:
        if self.active_trade is not None and self.active_trade.trade_id == ctx.trade_id:
            self.active_trade = None


class TradeLifecycleEngine:
    terminal_statuses = {TradeStatus.CLOSED, TradeStatus.CANCELLED}

    def create_trade(
        self,
        *,
        trade_id: int,
        key: str,
        direction: str,
        entry_key_bar_index: int,
        key_kline_ref: KlineRef,
        stoploss_atr_mult: float,
        entry_need_confirm: bool,
        exit_need_confirm: bool,
        enable_breakeven: bool,
        risk_reward_ratio: float,
        signal_metadata: dict[str, Any] | None = None,
    ) -> TradeContext:
        return TradeContext(
            trade_id=trade_id,
            key=key,
            direction=direction,
            order=None,
            entry_key_bar_index=int(entry_key_bar_index),
            key_kline_ref=key_kline_ref,
            stoploss_atr_mult=float(stoploss_atr_mult),
            status=TradeStatus.PENDING_ENTRY_CONFIRM if entry_need_confirm else TradeStatus.OPENING,
            entry_need_confirm=bool(entry_need_confirm),
            exit_need_confirm=bool(exit_need_confirm),
            enable_breakeven=bool(enable_breakeven),
            risk_reward_ratio=float(risk_reward_ratio),
            signal_metadata=dict(signal_metadata or {}),
        )

    def set_pending_exit_reason(
        self,
        ctx: TradeContext,
        code: str,
        label: str,
        detail: str | None = None,
        stop_multiple_r: float | None = None,
        risk_reward_ratio: float | None = None,
    ) -> None:
        ctx.pending_exit_reason = {
            "code": code,
            "label": label,
            "detail": detail,
            "stop_multiple_r": stop_multiple_r,
            "risk_reward_ratio": risk_reward_ratio,
        }
        ctx.requested_exit_reason_code = code
        ctx.requested_exit_reason_label = label
        ctx.requested_exit_reason_detail = detail

    def finalize_exit_reason(
        self,
        ctx: TradeContext,
        code: str,
        label: str,
        detail: str | None = None,
        stop_multiple_r: float | None = None,
        risk_reward_ratio: float | None = None,
    ) -> None:
        ctx.exit_reason_code = code
        ctx.exit_reason_label = label
        ctx.exit_reason_detail = detail
        ctx.stop_multiple_r = stop_multiple_r
        ctx.exit_risk_reward_ratio = risk_reward_ratio
        ctx.pending_exit_reason = None
        ctx.requested_exit_reason_code = None
        ctx.requested_exit_reason_label = None
        ctx.requested_exit_reason_detail = None

    def cancel_entry(self, ctx: TradeContext, reason: str) -> None:
        ctx.status = TradeStatus.CANCELLED
        ctx.cancel_reason = reason

    def mark_entry_opening(self, ctx: TradeContext, order: Any) -> None:
        ctx.order = order
        ctx.status = TradeStatus.OPENING

    def mark_entry_filled(self, ctx: TradeContext, *, price: float, fallback_stop_price: float) -> None:
        ctx.entry_price = float(price)
        ctx.status = TradeStatus.ACTIVE
        if ctx.initial_stop_price is None:
            ctx.initial_stop_price = float(fallback_stop_price)
        if ctx.stop_price is None:
            ctx.stop_price = float(ctx.initial_stop_price)
        ctx.breakeven_step = 0

    def request_exit(
        self,
        ctx: TradeContext,
        *,
        exit_key_bar_index: int,
        exit_key_ref: KlineRef,
        exit_need_confirm: bool,
        reason_code: str,
        reason_label: str,
        reason_detail: str | None = None,
    ) -> None:
        ctx.exit_need_confirm = bool(exit_need_confirm)
        ctx.exit_key_bar_index = int(exit_key_bar_index)
        ctx.exit_key_kline_ref = exit_key_ref
        self.set_pending_exit_reason(ctx, reason_code, reason_label, reason_detail)
        if ctx.exit_reason_code is None:
            ctx.exit_reason_code = reason_code
        if ctx.exit_reason_label is None:
            ctx.exit_reason_label = reason_label
        if ctx.exit_reason_detail is None and reason_detail is not None:
            ctx.exit_reason_detail = reason_detail
        if exit_need_confirm:
            ctx.status = TradeStatus.PENDING_EXIT_CONFIRM

    def mark_exit_closing(self, ctx: TradeContext, order: Any) -> None:
        ctx.order = order
        ctx.status = TradeStatus.CLOSING

    def mark_exit_confirm_failed(self, ctx: TradeContext) -> None:
        ctx.status = TradeStatus.ACTIVE
        ctx.exit_key_banned = True
        ctx.pending_exit_reason = None
        ctx.requested_exit_reason_code = None
        ctx.requested_exit_reason_label = None
        ctx.requested_exit_reason_detail = None

    def mark_exit_filled(self, ctx: TradeContext, *, price: float, value: float | None = None) -> None:
        ctx.exit_price = float(price)
        ctx.exit_value = float(value) if value is not None else None
        ctx.status = TradeStatus.CLOSED

    def mark_entry_failed(self, ctx: TradeContext, reason: str) -> None:
        ctx.status = TradeStatus.CANCELLED
        ctx.cancel_reason = reason
        ctx.order = None

    def mark_exit_failed(self, ctx: TradeContext) -> None:
        ctx.status = TradeStatus.ACTIVE
        ctx.order = None

    def calculate_stop_multiple_r(self, ctx: TradeContext, stop_price: float | None = None) -> float | None:
        if ctx.entry_price is None or ctx.initial_stop_price is None:
            return None
        entry_price = float(ctx.entry_price)
        initial_stop_price = float(ctx.initial_stop_price)
        active_stop_price = float(ctx.stop_price if stop_price is None else stop_price)
        risk = (entry_price - initial_stop_price) if ctx.direction == "LONG" else (initial_stop_price - entry_price)
        if risk <= 0.0:
            return None
        multiple = ((active_stop_price - entry_price) / risk) if ctx.direction == "LONG" else ((entry_price - active_stop_price) / risk)
        return round(float(multiple), 4)
