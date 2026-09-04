from __future__ import absolute_import, division, print_function, unicode_literals

import math
from datetime import datetime
from typing import Any, Dict, Optional, Set, Union

import backtrader as bt
from backtrader import num2date

from trader.common.config import DEFAULT_PERIOD
from trader.common.log_tag import LogTag
from trader.strategy.backtrader_adapter import BacktraderStrategyExecutionAdapter
from trader.strategy.lifecycle import (
    ORDER_ROLE_ENTRY,
    ORDER_ROLE_EXIT,
    ORDER_ROLE_KEY,
    ORDER_ROLE_STOP,
    ORDER_ROLE_TP,
    KlineRef,
    SignalSnapshot,
    TradeContext,
    TradeLifecycleEngine,
    TradeRegistry,
    TradeStatus,
)
from trader.strategy.risk import BREAKEVEN_EPS, StrategyRiskEngine
from trader.strategy.signal_router import SignalRouteActionType, SignalRouter, SignalRoutingState
from trader.utils.operate import Operate, OperateType
from trader.utils.trend import TrendType

_DEFAULT_POSITION_PRICE_BUFFER = 0.002  # 0.2% safety buffer for next-open fills


# chainer basic framework strategy
class BaseStrategy(bt.Strategy):
    params = (
        ("name", "Unkown"),
        ("mode", TrendType.NORMAL),
        ("period", DEFAULT_PERIOD),
        ("log", None),
        ("position", 0),
        ("trader", False),
        ("position_percent", 100),  # Position size as percentage of available cash (100 = full position)
        ("position_price_buffer", _DEFAULT_POSITION_PRICE_BUFFER),  # Safety buffer for sizing (next-open gap)
        # Chainer Framework v3: mode-based signal processing
        # - LONG_ONLY: long signal opens long, short signal closes long
        # - SHORT_ONLY: short signal opens short, long signal closes short
        # - BOTH: long signal opens long, short signal opens short, exit via stop/breakeven/TP
        ("chainer_mode", "LONG_ONLY"),  # LONG_ONLY, SHORT_ONLY, BOTH
        # Entry/Exit engine defaults (can be overridden per call)
        ("chainer_atr_period", 14),
        ("chainer_stoploss_atr_mult", 0.0),
        ("chainer_need_confirm", True),  # Require confirmation for both entry and exit
        ("chainer_enable_breakeven", True),
        ("chainer_risk_reward_ratio", 0.0),
        ("live_operation_sink", None),
        # When equity falls below this percentage of initial account value, new entries are disabled.
        # Existing positions continue to be managed (stoploss/breakeven/take-profit).
        ("chainer_min_equity_percent", 0.0),
    )

    TradeStatus = TradeStatus
    KlineRef = KlineRef
    TradeContext = TradeContext
    SignalSnapshot = SignalSnapshot

    def __init__(self):
        super().__init__()
        self.order = None
        self._initial_equity: Optional[float] = None

        # ATR must be initialized early if any logic depends on historical ATR values.
        # Backtrader indicators created later won't backfill history, which would make
        # stoploss_atr_mult ineffective for the first atrperiod bars after creation.
        self.atr = None
        if float(self.params.chainer_stoploss_atr_mult) != 0.0:
            self.atr = bt.indicators.ATR(self.datas[0], period=self.params.chainer_atr_period)

        # Entry/Exit engine state (lazy-activated when enter_trade/exit_trade is used)
        self._trade_registry = TradeRegistry()
        self._lifecycle = TradeLifecycleEngine()
        self._risk_engine = StrategyRiskEngine()
        self._signal_router = SignalRouter()
        self._bt_execution = BacktraderStrategyExecutionAdapter(self)
        self._trade_seq: int = self._trade_registry.trade_seq
        self._active_trade: Optional[BaseStrategy.TradeContext] = self._trade_registry.active_trade
        self._trades_by_id: Dict[int, BaseStrategy.TradeContext] = self._trade_registry.trades_by_id
        self._trades_by_key: Dict[str, BaseStrategy.TradeContext] = self._trade_registry.trades_by_key
        self._banned_entry_key_bar_index: Set[int] = self._trade_registry.banned_entry_key_bar_index
        self._banned_exit_key_bar_index: Set[int] = self._trade_registry.banned_exit_key_bar_index
        self._signal_snapshot: Optional[BaseStrategy.SignalSnapshot] = None

        self.start_time = datetime.fromtimestamp(0)
        self.end_time = datetime.fromtimestamp(0)

        # Track total bars as we process them
        self.total_bars = 0
        self._bars_counted = False

    def start(self):
        if self.params.position:
            # Note: Setting initial positions directly can cause issues with broker calculations
            # This feature is experimental and should be used with caution
            try:
                # Check if broker has cash set
                cash = self.broker.getcash()
                if cash > 0:
                    self.broker.positions[self.data] = bt.position.Position(size=self.params.position)
                    self.log_info(f"set first position:{self.params.position}")
                else:
                    self.log_info("Cannot set position without broker cash, skipping position initialization")
            except Exception as e:
                self.log_info(f"Failed to set initial position: {e}")

        # Capture initial equity for min-equity protection, if not already set
        try:
            if self._initial_equity is None:
                self._initial_equity = float(self.broker.getvalue())
        except Exception:
            # If broker value is not available yet, it will be lazily set later
            self._initial_equity = None

    def next(self):
        # Update total bars count as we process data
        if not self._bars_counted:
            # Try to get total bars from data buffer
            try:
                self.total_bars = self.datas[0].buflen()
                if self.total_bars > 0:
                    self._bars_counted = True
                    self.log_info(f"start:total_bars={self.total_bars}")
            except Exception:
                # Fallback: track as we go
                pass

        # Always update to current position + 1 as minimum
        current_bar = len(self)
        if current_bar > self.total_bars:
            self.total_bars = current_bar

        cur = self.cur_datetime()
        if cur > self.end_time:
            self.end_time = cur
        if int(self.start_time.timestamp()) == 0:
            self.start_time = cur

        self.log_debug(f"Kline:{cur} 收盘价, {self.data.close[0]:.2f}")

        self._process_signals()

        # Drive entry/exit engine if a trade exists
        self._process_trade_engine()

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        tradeid = getattr(order, "tradeid", None)
        role = getattr(order, "info", {}).get(ORDER_ROLE_KEY)

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log_info(
                    f"买入, 价格: {order.executed.price:.2f}, 花费: {order.executed.value:.2f}, "
                    f"手续费: {order.executed.comm:.2f}"
                )
            else:  # Sell
                self.log_info(
                    f"卖出, 价格: {order.executed.price:.2f}, 花费: {order.executed.value:.2f}, "
                    f"手续费: {order.executed.comm:.2f}"
                )
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            status_name = (
                "Canceled"
                if order.status == order.Canceled
                else "Margin"
                if order.status == order.Margin
                else "Rejected"
            )
            self.log_info(f"订单失败: status={status_name} role={role} trade_id={tradeid}")

        self.order = None

        # Sync entry/exit engine state with order completion (by tradeid)
        try:
            if tradeid is None:
                return
            ctx = self._trades_by_id.get(int(tradeid))
            if ctx is None:
                return

            if order.status in [order.Completed]:
                # Backward compatible fallback (when role is missing)
                is_entry = order.isbuy() if ctx.direction == "LONG" else order.issell()
                if role is None:
                    role = ORDER_ROLE_ENTRY if is_entry else ORDER_ROLE_EXIT

                if role == ORDER_ROLE_ENTRY:
                    fallback_stop = float(ctx.key_kline_ref.low) if ctx.direction == "LONG" else float(ctx.key_kline_ref.high)
                    self._lifecycle.mark_entry_filled(ctx, price=float(order.executed.price), fallback_stop_price=fallback_stop)
                    self.log_info(
                        f"交易入场成交: trade_id={ctx.trade_id} key={ctx.key} direction={ctx.direction} entry_price={ctx.entry_price:.6f} "
                        f"stop_price={ctx.stop_price:.6f}"
                    )
                    self._bt_execution.place_or_replace_stop(ctx)
                    tp_price = self._risk_engine.take_profit_price(ctx)
                    if tp_price is not None:
                        ctx.tp_price = float(tp_price)
                        self.log_info(
                            f"创建止盈订单: trade_id={ctx.trade_id} key={ctx.key} direction={ctx.direction} "
                            f"tp={ctx.tp_price:.6f} rr={ctx.risk_reward_ratio:.6f}"
                        )
                        self._bt_execution.place_or_replace_take_profit(ctx)
                else:
                    if role == ORDER_ROLE_STOP:
                        stop_multiple_r = self._lifecycle.calculate_stop_multiple_r(ctx)
                        if stop_multiple_r is None:
                            detail = "触发框架止损"
                        else:
                            smr = float(stop_multiple_r)
                            if abs(smr) <= BREAKEVEN_EPS:
                                kind = "保本"
                            elif smr > 0.0:
                                kind = "移动盈利"
                            else:
                                kind = "止损"
                            detail = f"触发框架止损（{kind}），止损位达到 {smr:.2f}R"
                        self._lifecycle.finalize_exit_reason(
                            ctx,
                            code="framework_stop",
                            label="框架止损退出",
                            detail=detail,
                            stop_multiple_r=stop_multiple_r,
                        )
                    elif role == ORDER_ROLE_TP:
                        rr = float(ctx.risk_reward_ratio)
                        detail = f"达到预设风险收益比 {rr:.2f}R" if rr > 0.0 else "达到预设风险收益比"
                        self._lifecycle.finalize_exit_reason(
                            ctx,
                            code="risk_reward_take_profit",
                            label="达到预设风险收益比退出",
                            detail=detail,
                            risk_reward_ratio=rr if rr > 0.0 else None,
                        )
                    else:
                        pending = dict(ctx.pending_exit_reason or {})
                        if not pending:
                            req_code = getattr(ctx, "requested_exit_reason_code", None)
                            req_label = getattr(ctx, "requested_exit_reason_label", None)
                            req_detail = getattr(ctx, "requested_exit_reason_detail", None)
                            if req_code is not None or req_label is not None or req_detail is not None:
                                pending = {
                                    "code": req_code,
                                    "label": req_label,
                                    "detail": req_detail,
                                }
                        self._lifecycle.finalize_exit_reason(
                            ctx,
                            code=str(pending.get("code") or "unclassified_exit"),
                            label=str(pending.get("label") or "未分类退出"),
                            detail=pending.get("detail"),
                            stop_multiple_r=pending.get("stop_multiple_r"),
                            risk_reward_ratio=pending.get("risk_reward_ratio"),
                        )
                    self._lifecycle.mark_exit_filled(
                        ctx,
                        price=float(order.executed.price),
                        value=float(order.executed.value),
                    )
                    if role == ORDER_ROLE_STOP:
                        low = float(self.data.low[0])
                        high = float(self.data.high[0])
                        stop_val = float(ctx.stop_price)
                        self.log_info(
                            f"止损成交出场: trade_id={ctx.trade_id} key={ctx.key} direction={ctx.direction} "
                            f"low={low:.6f} high={high:.6f} stop={stop_val:.6f} "
                            f"exit_price={ctx.exit_price:.6f}"
                        )
                    else:
                        self.log_info(
                            f"交易出场成交: trade_id={ctx.trade_id} key={ctx.key} "
                            f"direction={ctx.direction} exit_price={ctx.exit_price:.6f}"
                        )

                    self._bt_execution.cancel_stop(ctx)
                    self._bt_execution.cancel_take_profit(ctx)
                    if self._active_trade is not None and self._active_trade.trade_id == ctx.trade_id:
                        self._set_active_trade(None)
            elif order.status in [order.Canceled, order.Margin, order.Rejected]:
                status_name = (
                    "Canceled"
                    if order.status == order.Canceled
                    else "Margin"
                    if order.status == order.Margin
                    else "Rejected"
                )

                # Stop order cancellations are normal during stop replacement
                if role == ORDER_ROLE_STOP:
                    if order.status == order.Canceled:
                        self.log_info(
                            f"止损单取消(更新): trade_id={ctx.trade_id} key={ctx.key} stop={float(ctx.stop_price):.6f}"
                        )
                    else:
                        self.log_info(
                            f"止损单失败: status={status_name} trade_id={ctx.trade_id} key={ctx.key} "
                            f"stop={float(ctx.stop_price):.6f}"
                        )
                    if ctx.stop_order is not None and getattr(ctx.stop_order, "ref", None) == getattr(order, "ref", None):
                        ctx.stop_order = None
                    return

                if role == ORDER_ROLE_TP:
                    if order.status == order.Canceled:
                        self.log_info(
                            f"止盈单取消: trade_id={ctx.trade_id} key={ctx.key} tp={float(ctx.tp_price or 0.0):.6f}"
                        )
                    else:
                        self.log_info(
                            f"止盈单失败: status={status_name} trade_id={ctx.trade_id} key={ctx.key} "
                            f"tp={float(ctx.tp_price or 0.0):.6f}"
                        )
                    if ctx.tp_order is not None and getattr(ctx.tp_order, "ref", None) == getattr(order, "ref", None):
                        ctx.tp_order = None
                    return

                if role == ORDER_ROLE_ENTRY:
                    # Entry order did not fill -> cancel the trade context
                    self._lifecycle.mark_entry_failed(ctx, f"entry_order_{status_name.lower()}")
                    try:
                        cash = float(self.broker.getcash())
                        o_size = float(getattr(getattr(order, "created", None), "size", 0.0) or 0.0)
                        o_price = getattr(getattr(order, "created", None), "price", None)
                        o_price_f = float(o_price) if o_price is not None else 0.0
                        open_px = float(getattr(self.data, "open", [0.0])[0])
                        close_px = float(getattr(self.data, "close", [0.0])[0])
                        self.log_info(
                            f"进场订单失败详情: cash={cash:.2f} size={o_size:.8f} created_price={o_price_f:.6f} "
                            f"bar_open={open_px:.6f} bar_close={close_px:.6f}"
                        )
                    except Exception:
                        pass
                    self.log_info(
                        f"进场订单失败: status={status_name} trade_id={ctx.trade_id} key={ctx.key} -> 取消交易"
                    )
                    if self._active_trade is not None and self._active_trade.trade_id == ctx.trade_id:
                        self._set_active_trade(None)
                    return

                if role == ORDER_ROLE_EXIT:
                    # Exit order failed -> keep trade active
                    self._lifecycle.mark_exit_failed(ctx)
                    self.log_info(
                        f"出场订单失败: status={status_name} trade_id={ctx.trade_id} key={ctx.key}"
                    )
                    return
        except Exception as e:
            self.log_debug(f"notify_order: trade sync failed: {e}")

    def notify_trade(self, trade):
        if not trade.isclosed:
            return

        # Calculate profit percentage: (net_profit / entry_cost) * 100
        # Try to find the corresponding TradeContext to get accurate entry_price and exit_value
        ctx = None
        
        # Find the most recently closed trade context
        for trade_id, trade_ctx in self._trades_by_id.items():
            if trade_ctx.status == BaseStrategy.TradeStatus.CLOSED and trade_ctx.entry_price is not None:
                if ctx is None or trade_id > ctx.trade_id:
                    ctx = trade_ctx
        
        if ctx is not None and ctx.entry_price is not None and ctx.exit_price is not None:
            entry_price = float(ctx.entry_price)
            exit_price = float(ctx.exit_price)
            
            # Calculate position size from exit_value if available, otherwise from gross profit
            if ctx.exit_value is not None and ctx.exit_value > 0:
                size = ctx.exit_value / exit_price
            else:
                # Fallback: estimate size from gross profit
                price_diff = exit_price - entry_price if ctx.direction == "LONG" else entry_price - exit_price
                if price_diff != 0 and trade.pnl != 0:
                    size = abs(trade.pnl / price_diff)
                else:
                    size = 0
            
            if size > 0:
                # Entry cost = entry_price * size (commission is already deducted in pnlcomm)
                entry_cost = entry_price * size
                profit_pct = (trade.pnlcomm / entry_cost * 100) if entry_cost > 0 else 0.0
            else:
                profit_pct = 0.0
        else:
            # Fallback: cannot calculate accurately without trade context
            profit_pct = 0.0

        self.log_info(
            f"营业利润, 毛利润: {trade.pnl:.2f}, 净利润: {trade.pnlcomm:.2f}, "
            f"盈利百分比: {profit_pct:.2f}%"
        )

    def log_info(self, msg):
        cur_time = self.cur_datetime()
        if self.bar_idx() < 0:
            cur_time = "not_started"
        if self.params.log is None:
            print(f"[{cur_time}] {msg}")
            return
        self.params.log.info(
            f"[{cur_time}] {msg}, [{self.name()}][{self.bar_idx()}/{self.total_bars-1}]",
            LogTag.STRATEGY,
        )

    def log_debug(self, msg):
        cur_time = self.cur_datetime()
        if self.bar_idx() < 0:
            cur_time = "not_started"
        if self.params.log is None:
            print(f"[{cur_time}] {msg}")
            return
        bars_info = ""
        if self.total_bars > 0:
            bars_info = f"[{self.bar_idx()}/{self.total_bars-1}]"
        self.params.log.debug(
            f"[{cur_time}] {msg}, [{self.name()}]{bars_info}",
            LogTag.STRATEGY,
        )

    def cur_datetime(self):
        try:
            return num2date(self.datas[0].datetime[0])
        except (IndexError, ValueError):
            return datetime.fromtimestamp(0)

    def bar_idx(self):
        return len(self) - 1

    def _ensure_atr_indicator(self):
        if hasattr(self, "atr") and self.atr is not None:
            return
        self.atr = bt.indicators.ATR(self.datas[0], period=self.params.chainer_atr_period)

    def _atr_value_for_key_bar(self, key_bar_index: int) -> float:
        self._ensure_atr_indicator()
        shift = int(key_bar_index) - self.bar_idx()
        if self.atr is None:
            return 0.0
        for attempt_shift in [shift, 0]:
            try:
                val = self.atr[attempt_shift]
                if val is not None:
                    val_float = float(val)
                    if not (math.isnan(val_float) or math.isinf(val_float)):
                        return val_float
            except (IndexError, TypeError, ValueError):
                continue
        return 0.0

    def _kline_ref_by_bar_index(self, key_bar_index: int) -> "BaseStrategy.KlineRef":
        if key_bar_index is None:
            raise ValueError("key_bar_index is required")
        kbi = int(key_bar_index)
        shift = kbi - self.bar_idx()
        if shift > 0:
            raise ValueError("key_bar_index must not be in the future")
        dt = num2date(self.datas[0].datetime[shift])
        high = float(self.datas[0].high[shift])
        low = float(self.datas[0].low[shift])
        return BaseStrategy.KlineRef(dt=dt, high=high, low=low)

    def _default_trade_key(self, ref: "BaseStrategy.KlineRef") -> str:
        return ref.dt.strftime("%Y%m%d%H%M")

    def _allocate_trade_id(self) -> int:
        self._trade_seq = self._trade_registry.allocate_trade_id()
        return self._trade_seq

    def _register_trade(self, ctx: "BaseStrategy.TradeContext") -> None:
        self._trade_registry.register(ctx)

    def _set_active_trade(self, ctx: Optional["BaseStrategy.TradeContext"]) -> None:
        self._active_trade = ctx
        self._trade_registry.active_trade = ctx

    def enter_trade(
        self,
        trade_key: Any = None,
        direction: str = "LONG",
        key_bar_index: int = 0,
        stoploss_atr_mult: Optional[float] = None,
        need_confirm: Optional[bool] = None,
        enable_breakeven: Optional[bool] = None,
        risk_reward_ratio: Optional[float] = None,
        signal_metadata: Optional[Dict[str, Any]] = None,
    ) -> "BaseStrategy.TradeContext":
        """
        Create a trade context and optionally place entry order.

        If need_confirm is enabled,
        entry order will be placed only when close > key_high; it will be cancelled
        when close < key_low and the key time will be banned for future confirmations.
        """
        if direction is None:
            direction = "LONG"
        direction_norm = str(direction).upper()
        if direction_norm not in ("LONG", "SHORT"):
            raise ValueError("direction must be LONG or SHORT")
        mode = str(self.params.chainer_mode).upper()
        short_allowed = mode in ("SHORT_ONLY", "BOTH")
        if direction_norm == "SHORT" and not short_allowed:
            raise ValueError("SHORT is disabled in LONG_ONLY mode")

        if self._active_trade is not None and self._active_trade.status not in (
            BaseStrategy.TradeStatus.CLOSED,
            BaseStrategy.TradeStatus.CANCELLED,
        ):
            raise RuntimeError("Only one active trade is allowed at a time")

        key_ref = self._kline_ref_by_bar_index(key_bar_index)

        base_key = ""
        if trade_key is None or str(trade_key).strip() == "":
            base_key = self._default_trade_key(key_ref)
        else:
            base_key = str(trade_key)

        trade_id = self._allocate_trade_id()
        key = base_key
        if key in self._trades_by_key:
            key = f"{base_key}-{trade_id}"

        sl_atr_mult = float(self.params.chainer_stoploss_atr_mult if stoploss_atr_mult is None else stoploss_atr_mult)
        # Entry confirmation (independent of direction/mode, controlled by chainer_need_confirm)
        if need_confirm is not None:
            entry_need_confirm = bool(need_confirm)
        else:
            entry_need_confirm = bool(self.params.chainer_need_confirm)
        breakeven_on = bool(self.params.chainer_enable_breakeven if enable_breakeven is None else enable_breakeven)
        rr = float(self.params.chainer_risk_reward_ratio if risk_reward_ratio is None else risk_reward_ratio)
        # Exit confirmation (independent of direction/mode, controlled by chainer_need_confirm)
        exit_need_confirm = bool(self.params.chainer_need_confirm)

        ctx = self._lifecycle.create_trade(
            trade_id=trade_id,
            key=key,
            direction=direction_norm,
            entry_key_bar_index=int(key_bar_index),
            key_kline_ref=key_ref,
            stoploss_atr_mult=sl_atr_mult,
            entry_need_confirm=entry_need_confirm,
            exit_need_confirm=exit_need_confirm,
            enable_breakeven=breakeven_on,
            risk_reward_ratio=rr,
            signal_metadata=dict(signal_metadata or {}),
        )

        if int(key_bar_index) in self._banned_entry_key_bar_index:
            self._lifecycle.cancel_entry(ctx, "entry_key_banned")
            ctx.entry_key_banned = True
            self._register_trade(ctx)
            self.log_info(f"进场忽略(已禁用关键K): trade_id={ctx.trade_id} key={ctx.key} key_bar_index={int(key_bar_index)}")
            return ctx

        atr_val = self._atr_value_for_key_bar(key_bar_index) if sl_atr_mult != 0.0 else 0.0
        stop_price = self._risk_engine.initial_stop_price(
            direction=ctx.direction,
            key_low=float(key_ref.low),
            key_high=float(key_ref.high),
            stoploss_atr_mult=sl_atr_mult,
            atr_value=atr_val,
            signal_metadata=ctx.signal_metadata,
        )

        ctx.initial_stop_price = stop_price
        ctx.stop_price = stop_price

        self._register_trade(ctx)
        self._set_active_trade(ctx)

        self.log_info(
            f"创建交易(进场): trade_id={ctx.trade_id} key={ctx.key} direction={ctx.direction} need_confirm={1 if ctx.entry_need_confirm else 0} "
            f"key_time={ctx.key_kline_ref.dt} key_high={ctx.key_kline_ref.high:.6f} key_low={ctx.key_kline_ref.low:.6f} "
            f"stop_price={ctx.stop_price:.6f} sl_atr_mult={ctx.stoploss_atr_mult:.6f} rr={ctx.risk_reward_ratio:.6f} "
            f"breakeven={1 if ctx.enable_breakeven else 0}"
        )

        if not ctx.entry_need_confirm:
            order = self._bt_execution.open_entry(ctx)
            self._lifecycle.mark_entry_opening(ctx, order)
            self.order = order
            if ctx.direction == "LONG":
                self.log_info(f"创建买入订单: trade_id={ctx.trade_id} key={ctx.key}")
                self.log_info("下单时机: 本K线收盘确认后提交市价单，默认在下一根K线开盘成交")
            else:
                self.log_info(f"创建卖出订单(开空): trade_id={ctx.trade_id} key={ctx.key}")
                self.log_info("下单时机: 本K线收盘确认后提交市价单，默认在下一根K线开盘成交")

        return ctx

    def exit_trade(
        self,
        trade_ref: Optional[Union[int, str]] = None,
        key_bar_index: int = 0,
        need_confirm: Optional[bool] = None,
        exit_reason_code: Optional[str] = None,
        exit_reason_label: Optional[str] = None,
        exit_reason_detail: Optional[str] = None,
    ) -> Optional["BaseStrategy.TradeContext"]:
        """
        Request exit for a trade by id/key. If trade_ref is None, uses current active trade.

        If need_confirm is enabled, exit order will be placed only when close < key_low; it will be
        cancelled when close > key_high and the key time will be banned for future confirmations.
        """
        ctx: Optional[BaseStrategy.TradeContext] = None
        if trade_ref is None:
            ctx = self._active_trade
        elif isinstance(trade_ref, int):
            ctx = self._trades_by_id.get(int(trade_ref))
        else:
            ref_str = str(trade_ref)
            if ref_str.isdigit():
                ctx = self._trades_by_id.get(int(ref_str))
            else:
                ctx = self._trades_by_key.get(ref_str)

        if ctx is None:
            return None
        if ctx.status not in (BaseStrategy.TradeStatus.ACTIVE, BaseStrategy.TradeStatus.PENDING_EXIT_CONFIRM):
            return ctx

        # Exit uses the unified exit confirmation parameter
        if need_confirm is not None:
            exit_need_confirm = bool(need_confirm)
        else:
            exit_need_confirm = bool(self.params.chainer_need_confirm)
        exit_key_ref = self._kline_ref_by_bar_index(key_bar_index)
        if int(key_bar_index) in self._banned_exit_key_bar_index:
            ctx.exit_key_banned = True
            self.log_info(f"出场忽略(已禁用关键K): trade_id={ctx.trade_id} key={ctx.key} key_bar_index={int(key_bar_index)}")
            return ctx

        self.log_info(
            f"请求出场: trade_id={ctx.trade_id} key={ctx.key} need_confirm={1 if exit_need_confirm else 0} "
            f"key_time={exit_key_ref.dt} key_high={exit_key_ref.high:.6f} key_low={exit_key_ref.low:.6f}"
        )
        self._lifecycle.request_exit(
            ctx,
            exit_key_bar_index=key_bar_index,
            exit_key_ref=exit_key_ref,
            exit_need_confirm=exit_need_confirm,
            reason_code=exit_reason_code or "unclassified_exit",
            reason_label=exit_reason_label or "未分类退出",
            reason_detail=exit_reason_detail,
        )

        if not exit_need_confirm:
            # For immediate exits, cancel any existing stop/tp orders to ensure 
            # the market order takes precedence and fills at the next open (or current close if CoC).
            self._bt_execution.cancel_stop(ctx)
            self._bt_execution.cancel_take_profit(ctx)
            close_size = self._bt_execution.close_size()
            if close_size <= 0.0:
                self.log_info(f"创建卖出订单失败(无持仓): trade_id={ctx.trade_id} key={ctx.key}")
                return ctx
            order = self._bt_execution.close_position(ctx)
            if order is None:
                self.log_info(f"创建平仓订单失败: trade_id={ctx.trade_id} key={ctx.key}")
                return ctx
            self._lifecycle.mark_exit_closing(ctx, order)
            self.order = order
            self.log_info(f"创建平仓订单: trade_id={ctx.trade_id} key={ctx.key} size={close_size}")

        return ctx

    def get_long_signal(self) -> bool:
        """
        Override in subclass to generate long signal (做多信号).

        Signal semantics are fixed: this always represents the condition to go long.
        For MA Cross example: golden cross (fast crosses above slow).

        Returns:
            bool: True when long condition is met.
        """
        return False

    def get_short_signal(self) -> bool:
        """
        Override in subclass to generate short signal (做空信号).

        Signal semantics are fixed: this always represents the condition to go short.
        For MA Cross example: death cross (fast crosses below slow).

        Returns:
            bool: True when short condition is met.
        """
        return False

    def get_long_signal_context(self) -> Dict[str, Any]:
        """Override in subclass to provide structured metadata for a LONG signal."""
        return {}

    def get_short_signal_context(self) -> Dict[str, Any]:
        """Override in subclass to provide structured metadata for a SHORT signal."""
        return {}

    def on_signal_lifecycle_event(
        self,
        event_type: str,
        direction: str,
        signal_context: Optional[Dict[str, Any]] = None,
        **payload: Any,
    ) -> None:
        """Override in subclass to observe framework-managed signal lifecycle events."""
        return None

    def _emit_signal_lifecycle_event(
        self,
        event_type: str,
        direction: str,
        signal_context: Optional[Dict[str, Any]] = None,
        **payload: Any,
    ) -> None:
        self.on_signal_lifecycle_event(
            event_type,
            direction,
            dict(signal_context or {}),
            **payload,
        )

    def _signal_snapshot_for_current_bar(self) -> "BaseStrategy.SignalSnapshot":
        bar_index = self.bar_idx()
        snapshot = self._signal_snapshot
        if snapshot is not None and snapshot.bar_index == bar_index:
            return snapshot

        long_signal = bool(self.get_long_signal())
        short_signal = bool(self.get_short_signal())
        long_context = dict(self.get_long_signal_context() or {}) if long_signal else {}
        short_context = dict(self.get_short_signal_context() or {}) if short_signal else {}
        snapshot = BaseStrategy.SignalSnapshot(
            bar_index=bar_index,
            long_signal=long_signal,
            short_signal=short_signal,
            long_context=long_context,
            short_context=short_context,
        )
        self._signal_snapshot = snapshot
        return snapshot

    def _process_signals(self) -> None:
        """
        Process long/short signals through the framework signal router.
        """
        snapshot = self._signal_snapshot_for_current_bar()
        mode = str(self.params.chainer_mode).upper()
        if mode not in ("LONG_ONLY", "SHORT_ONLY", "BOTH"):
            mode = "LONG_ONLY"
        if snapshot.long_signal or snapshot.short_signal:
            self.log_debug(f"信号触发: mode={mode} long_signal={snapshot.long_signal} short_signal={snapshot.short_signal}")

        actions = self._signal_router.route(
            snapshot,
            SignalRoutingState(
                mode=mode,
                can_open_new_position=self._can_open_new_position(),
                active_trade=self._active_trade,
                position_size=float(getattr(self.position, "size", 0.0)),
            ),
        )
        for action in actions:
            if action.action_type == SignalRouteActionType.DETECTED:
                self._emit_signal_lifecycle_event("detected", action.direction, action.context)
                continue
            if action.action_type == SignalRouteActionType.BLOCKED:
                self._emit_signal_lifecycle_event(
                    "blocked",
                    action.direction,
                    action.context,
                    reason=action.reason,
                    active_trade=action.active_trade,
                )
                continue
            if action.action_type == SignalRouteActionType.ENTER:
                if mode == "LONG_ONLY" and action.direction == "LONG":
                    self.log_info("LONG_ONLY模式: 检测到做多信号，尝试开多仓")
                elif mode == "SHORT_ONLY" and action.direction == "SHORT":
                    self.log_info("SHORT_ONLY模式: 检测到做空信号，尝试开空仓")
                try:
                    ctx = self.enter_trade(
                        direction=action.direction,
                        key_bar_index=self.bar_idx(),
                        signal_metadata=action.context,
                    )
                    event_type = "entry_context_cancelled" if ctx.status == BaseStrategy.TradeStatus.CANCELLED else "entry_context_created"
                    self._emit_signal_lifecycle_event(
                        event_type,
                        action.direction,
                        action.context,
                        reason=ctx.cancel_reason,
                        trade_context=ctx,
                        trade_id=int(ctx.trade_id),
                    )
                except (ValueError, RuntimeError) as e:
                    self.log_debug(f"_process_signals: enter_trade {action.direction} failed: {e}")
                continue
            if action.action_type == SignalRouteActionType.EXIT:
                if mode == "LONG_ONLY":
                    self.log_info("LONG_ONLY模式: 检测到做空信号，尝试平多仓")
                elif mode == "SHORT_ONLY":
                    self.log_info("SHORT_ONLY模式: 检测到做多信号，尝试平空仓")
                try:
                    self._emit_signal_lifecycle_event("exit_requested", action.direction, action.context, reason=action.reason)
                    self.exit_trade(
                        key_bar_index=self.bar_idx(),
                        exit_reason_code=action.exit_reason_code,
                        exit_reason_label=action.exit_reason_label,
                        exit_reason_detail=action.exit_reason_detail,
                    )
                except (ValueError, RuntimeError) as e:
                    self.log_debug(f"_process_signals: exit_trade failed: {e}")

    def _process_trade_engine(self) -> None:
        ctx = self._active_trade
        if ctx is None:
            return

        # Entry confirmation
        if ctx.status == BaseStrategy.TradeStatus.PENDING_ENTRY_CONFIRM:
            close = float(self.data.close[0])
            key_high = float(ctx.key_kline_ref.high)
            key_low = float(ctx.key_kline_ref.low)
            confirm_ok = close > key_high if ctx.direction == "LONG" else close < key_low
            confirm_fail = close < key_low if ctx.direction == "LONG" else close > key_high

            # If opposing signal appears before confirmation, cancel this trade.
            # This matches TradingView behavior: confirmation is invalid once an opposing signal appears.
            snapshot = self._signal_snapshot_for_current_bar()
            long_signal = snapshot.long_signal
            short_signal = snapshot.short_signal
            mode = str(self.params.chainer_mode).upper()
            if mode not in ("LONG_ONLY", "SHORT_ONLY", "BOTH"):
                mode = "LONG_ONLY"

            # Determine if opposing signal appeared
            # For LONG entry pending: short signal is the exit signal
            # For SHORT entry pending: long signal is the exit signal
            # In BOTH mode, no opposing signal logic (entries are independent)
            opposing_signal = False
            if mode == "LONG_ONLY" and ctx.direction == "LONG":
                opposing_signal = short_signal
            elif mode == "SHORT_ONLY" and ctx.direction == "SHORT":
                opposing_signal = long_signal
            # In BOTH mode, no opposing signal cancels entry

            if opposing_signal:
                self._lifecycle.cancel_entry(ctx, "entry_pending_exit_signal")
                self._banned_entry_key_bar_index.add(int(ctx.entry_key_bar_index))
                if ctx.direction == "LONG":
                    self.log_info(
                        f"进场取消(未确认前出现出场信号): trade_id={ctx.trade_id} key={ctx.key} close={close:.6f}"
                    )
                else:
                    self.log_info(
                        f"进场取消(未确认前出现出场信号): trade_id={ctx.trade_id} key={ctx.key} close={close:.6f}"
                    )
                self._set_active_trade(None)
                return

            # If equity protection is enabled and current equity is below threshold,
            # cancel the pending entry as if confirmation failed.
            if not self._can_open_new_position():
                self._lifecycle.cancel_entry(ctx, "entry_equity_below_min")
                self._banned_entry_key_bar_index.add(int(ctx.entry_key_bar_index))
                self.log_info(
                    f"进场取消(账户净值低于最小进场阈值): trade_id={ctx.trade_id} key={ctx.key} close={close:.6f}"
                )
                self._set_active_trade(None)
                return

            if confirm_ok:
                order = (
                    self._bt_execution.open_entry(ctx)
                )
                self._lifecycle.mark_entry_opening(ctx, order)
                self.order = order
                if ctx.direction == "LONG":
                    self.log_info(f"进场确认成功: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f} > key_high")
                    self.log_info(f"创建买入订单: trade_id={ctx.trade_id} key={ctx.key}")
                    self.log_info("下单时机: 本K线收盘确认后提交市价单，默认在下一根K线开盘成交")
                else:
                    self.log_info(f"进场确认成功: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f} < key_low")
                    self.log_info(f"创建卖出订单(开空): trade_id={ctx.trade_id} key={ctx.key}")
                    self.log_info("下单时机: 本K线收盘确认后提交市价单，默认在下一根K线开盘成交")
            elif confirm_fail:
                self._lifecycle.cancel_entry(ctx, "entry_confirm_failed")
                self._banned_entry_key_bar_index.add(int(ctx.entry_key_bar_index))
                if ctx.direction == "LONG":
                    self.log_info(f"进场确认失败: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f} < key_low")
                else:
                    self.log_info(f"进场确认失败: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f} > key_high")
                self._set_active_trade(None)
            return

        # Exit confirmation
        if ctx.status == BaseStrategy.TradeStatus.PENDING_EXIT_CONFIRM and ctx.exit_key_kline_ref is not None:
            close = float(self.data.close[0])
            key_low = float(ctx.exit_key_kline_ref.low)
            key_high = float(ctx.exit_key_kline_ref.high)
            confirm_ok = close < key_low if ctx.direction == "LONG" else close > key_high
            confirm_fail = close > key_high if ctx.direction == "LONG" else close < key_low
            if confirm_ok:
                oco_order = ctx.stop_order if ctx.stop_order is not None and ctx.tp_order is None else None
                if oco_order is None:
                    self._bt_execution.cancel_stop(ctx)
                self._bt_execution.cancel_take_profit(ctx)
                close_size = self._bt_execution.close_size()
                if close_size <= 0.0:
                    self.log_info(f"创建卖出订单失败(无持仓): trade_id={ctx.trade_id} key={ctx.key}")
                    return
                order = self._bt_execution.close_position(ctx, oco_order=oco_order)
                if order is None:
                    self.log_info(f"创建平仓订单失败: trade_id={ctx.trade_id} key={ctx.key}")
                    return
                self._lifecycle.mark_exit_closing(ctx, order)
                self.order = order
                if ctx.direction == "LONG":
                    self.log_info(f"出场确认成功: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f} < key_low")
                else:
                    self.log_info(f"出场确认成功: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f} > key_high")
                self.log_info(f"创建平仓订单: trade_id={ctx.trade_id} key={ctx.key} size={close_size}")
            elif confirm_fail:
                self._lifecycle.mark_exit_confirm_failed(ctx)
                if ctx.exit_key_bar_index is not None:
                    self._banned_exit_key_bar_index.add(int(ctx.exit_key_bar_index))
                if ctx.direction == "LONG":
                    self.log_info(f"出场确认失败: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f} > key_high")
                else:
                    self.log_info(f"出场确认失败: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f} < key_low")
            return

        # Stop-loss and breakeven only apply after entry fill
        if ctx.status != BaseStrategy.TradeStatus.ACTIVE:
            return
        if ctx.entry_price is None or ctx.stop_price is None or ctx.initial_stop_price is None:
            return

        adjustment = self._risk_engine.breakeven_adjustment(ctx, close_price=float(self.data.close[0]))
        if adjustment is not None:
            ctx.stop_price = float(adjustment.new_stop)
            ctx.breakeven_step = int(adjustment.step)
            self.log_info(
                f"保本移动止损: trade_id={ctx.trade_id} key={ctx.key} direction={ctx.direction} "
                f"step={ctx.breakeven_step} stop={ctx.stop_price:.6f}"
            )
            self._emit_breakeven_operation(ctx, old_stop=adjustment.old_stop, new_stop=adjustment.new_stop)
            self._bt_execution.place_or_replace_stop(ctx)

        # Ensure a standing stop exists during ACTIVE trade (covers cases where the stop
        # order was cancelled externally or not created due to sizing issues).
        if ctx.stop_price is not None and (ctx.stop_order is None or not getattr(ctx.stop_order, "alive", lambda: False)()):
            self._bt_execution.place_or_replace_stop(ctx)

        # Ensure a standing TP exists during ACTIVE trade when enabled.
        if ctx.tp_price is not None and (ctx.tp_order is None or not getattr(ctx.tp_order, "alive", lambda: False)()):
            self._bt_execution.place_or_replace_take_profit(ctx)

    def name(self):
        return self.params.name

    def _emit_breakeven_operation(self, ctx: "BaseStrategy.TradeContext", *, old_stop: float, new_stop: float) -> None:
        sink = getattr(self.params, "live_operation_sink", None)
        if sink is None:
            return
        op = Operate(OperateType.RISK_UPDATE, int(self.cur_datetime().timestamp()), float(new_stop))
        op.trigger_reason = "breakeven_move"
        op.stop_loss = float(new_stop)
        op.breakeven_old_stop = float(old_stop)
        op.breakeven_new_stop = float(new_stop)
        op.breakeven_step = int(ctx.breakeven_step)
        op.signal_metadata = dict(ctx.signal_metadata or {})
        signal_event_id = op.signal_metadata.get("signal_event_id") or op.signal_metadata.get("event_id")
        if signal_event_id:
            op.signal_event_id = signal_event_id
        op.framework_trade = {
            "trade_id": ctx.trade_id,
            "direction": ctx.direction,
            "initial_stop_price": ctx.initial_stop_price,
            "stop_price": ctx.stop_price,
            "take_profit": ctx.tp_price,
            "risk_reward_ratio": ctx.risk_reward_ratio,
            "breakeven_step": ctx.breakeven_step,
        }
        sink(op)

    def set_default_period(self, period):
        if self.params.period == DEFAULT_PERIOD:
            self.params.period = period

    def can_trade(self):
        if self.params.trader:
            if self.bar_idx() + 2 >= self.total_bars:
                return True
            return False
        return True

    def _calculate_position_size(self, price=None):
        """
        Calculate position size based on position_percent parameter.
        
        Args:
            price: Price to use for calculation. If None, uses current close price.
            
        Returns:
            float: Calculated position size (number of units). Use float to support
            fractional sizing (e.g. crypto spot).
        """
        if price is None:
            price = self.data.close[0]
        
        # Validate price is positive before division
        if price <= 0:
            self.log_debug(f"Invalid price for position calculation: {price}. Returning 0 position size.")
            return 0
        
        cash = self.broker.getcash()
        commission_info = self.broker.getcommissioninfo(self.data)
        commission_rate = commission_info.p.commission
        
        # Calculate available cash based on position_percent
        available_cash = cash * (self.params.position_percent / 100.0)
        
        # Calculate position size considering commission
        # Formula: size = available_cash / (price * (1 + commission_rate))
        size = available_cash / (price * (1 + commission_rate))
        
        return float(size) if size > 0 else 0.0

    def _can_open_new_position(self) -> bool:
        """
        Check whether new positions are allowed based on current equity and
        chainer_min_equity_percent parameter.

        When chainer_min_equity_percent <= 0, this check is disabled.
        """
        try:
            min_pct = float(getattr(self.params, "chainer_min_equity_percent", 0.0) or 0.0)
        except Exception:
            min_pct = 0.0

        if min_pct <= 0.0:
            return True

        try:
            equity = float(self.broker.getvalue())
        except Exception as exc:
            self.log_debug(f"_can_open_new_position: failed to get equity: {exc}")
            return True

        if self._initial_equity is None or self._initial_equity <= 0.0:
            self._initial_equity = equity
            return True

        threshold = self._initial_equity * (min_pct / 100.0)
        return equity >= threshold

    def buy(
        self,
        data=None,
        size=None,
        price=None,
        plimit=None,
        exectype=None,
        valid=None,
        tradeid=0,
        oco=None,
        trailamount=None,
        trailpercent=None,
        parent=None,
        transmit=True,
        **kwargs,
    ):
        """
        Override buy method to automatically apply position_percent when size is not specified.
        
        If size is provided, uses it directly (maintains backward compatibility).
        If size is None, calculates it based on position_percent parameter.
        """
        if size is None:
            if price is None:
                buffer_pct = float(getattr(self.params, "position_price_buffer", _DEFAULT_POSITION_PRICE_BUFFER))
                est_price = float(self.data.close[0]) * (1.0 + max(0.0, buffer_pct))
                size = self._calculate_position_size(price=est_price)
            else:
                size = self._calculate_position_size(price=price)
            if size <= 0:
                self.log_debug("Calculated position size is 0 or negative, skipping buy order")
                return None
        
        return super().buy(
            data=data,
            size=size,
            price=price,
            plimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            oco=oco,
            trailamount=trailamount,
            trailpercent=trailpercent,
            parent=parent,
            transmit=transmit,
            **kwargs
        )

    def sell(
        self,
        data=None,
        size=None,
        price=None,
        plimit=None,
        exectype=None,
        valid=None,
        tradeid=0,
        oco=None,
        trailamount=None,
        trailpercent=None,
        parent=None,
        transmit=True,
        **kwargs,
    ):
        """
        Override sell method to automatically apply position_percent when size is not specified.
        
        If size is provided, uses it directly (maintains backward compatibility).
        If size is None, calculates it based on position_percent parameter.
        """
        if size is None:
            if price is None:
                buffer_pct = float(getattr(self.params, "position_price_buffer", _DEFAULT_POSITION_PRICE_BUFFER))
                est_price = float(self.data.close[0]) * (1.0 + max(0.0, buffer_pct))
                size = self._calculate_position_size(price=est_price)
            else:
                size = self._calculate_position_size(price=price)
            if size <= 0:
                self.log_debug("Calculated position size is 0 or negative, skipping sell order")
                return None
        
        return super().sell(
            data=data,
            size=size,
            price=price,
            plimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            oco=oco,
            trailamount=trailamount,
            trailpercent=trailpercent,
            parent=parent,
            transmit=transmit,
            **kwargs
        )
