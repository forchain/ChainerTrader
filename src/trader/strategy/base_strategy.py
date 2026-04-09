from __future__ import absolute_import, division, print_function, unicode_literals

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Set, Union

import backtrader as bt
from backtrader import num2date

from trader.common.config import DEFAULT_PERIOD
from trader.common.log_tag import LogTag
from trader.libraries.chainer_trader import ChainerTraderLib
from trader.utils.trend import TrendType

_BREAKEVEN_EPS = 1e-10
_ORDER_ROLE_KEY = "chainer_role"
_ORDER_ROLE_ENTRY = "entry"
_ORDER_ROLE_EXIT = "exit"
_ORDER_ROLE_STOP = "stop"
_ORDER_ROLE_TP = "take_profit"
_DEFAULT_POSITION_PRICE_BUFFER = 0.002  # 0.2% safety buffer for next-open fills


# chainer basic framework strategy
class BaseStrategy(bt.Strategy):
    params = (
        ("name", "Unkown"),
        ("atr", False),
        ("atrperiod", 14),
        ("atrdist", 5),  # ATR distance for stop price
        ("mode", TrendType.NORMAL),
        ("period", DEFAULT_PERIOD),
        ("log", None),
        ("stoploss", False),
        ("takeprofit", False),
        ("position", 0),
        ("trader", False),
        ("position_percent", 100),  # Position size as percentage of available cash (100 = full position)
        ("position_price_buffer", _DEFAULT_POSITION_PRICE_BUFFER),  # Safety buffer for sizing (next-open gap)
        # Chainer Framework v3: mode-based signal processing
        # - LONG_ONLY: long signal opens long, short signal closes long
        # - SHORT_ONLY: short signal opens short, long signal closes short
        # - BOTH: long signal opens long, short signal opens short, exit via stop/breakeven/TP
        ("chainer_mode", "LONG_ONLY"),  # LONG_ONLY, SHORT_ONLY, BOTH
        ("chainer_auto_signal", False),  # Enable auto signal processing via get_long_signal/get_short_signal
        # Entry/Exit engine defaults (can be overridden per call)
        ("chainer_stoploss_atr_mult", 0.0),
        ("chainer_enter_need_confirm", True),  # Require confirmation for entry signal
        ("chainer_exit_need_confirm", True),   # Require confirmation for exit signal
        ("chainer_enable_breakeven", True),
        ("chainer_risk_reward_ratio", 0.0),
        # When equity falls below this percentage of initial account value, new entries are disabled.
        # Existing positions continue to be managed (stoploss/breakeven/take-profit).
        ("chainer_min_equity_percent", 0.0),
    )

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
        order: Optional[bt.Order]
        entry_key_bar_index: int
        key_kline_ref: "BaseStrategy.KlineRef"
        stoploss_atr_mult: float

        # Runtime fields
        status: "BaseStrategy.TradeStatus"
        entry_need_confirm: bool
        exit_need_confirm: bool
        enable_breakeven: bool
        risk_reward_ratio: float

        entry_price: Optional[float] = None
        exit_price: Optional[float] = None
        exit_value: Optional[float] = None  # Exit order value for profit calculation
        tp_price: Optional[float] = None
        signal_metadata: Optional[Dict[str, Any]] = None

        initial_stop_price: Optional[float] = None
        stop_price: Optional[float] = None
        breakeven_step: int = 0

        entry_key_banned: bool = False
        exit_key_banned: bool = False
        exit_key_bar_index: Optional[int] = None
        exit_key_kline_ref: Optional["BaseStrategy.KlineRef"] = None

        cancel_reason: Optional[str] = None
        stop_order: Optional[bt.Order] = None
        tp_order: Optional[bt.Order] = None

    def __init__(self):
        super().__init__()
        self.order = None
        self._initial_equity: Optional[float] = None

        # Stop loss point
        if self.params.stoploss:
            self.stopLossPoint = 0

        # take profit
        if self.params.takeprofit:
            self.takeProfitPoint = 0

        # ATR must be initialized early if any logic depends on historical ATR values.
        # Backtrader indicators created later won't backfill history, which would make
        # stoploss_atr_mult ineffective for the first atrperiod bars after creation.
        if bool(self.params.atr) or float(self.params.chainer_stoploss_atr_mult) != 0.0:
            self.atr = bt.indicators.ATR(self.datas[0], period=self.params.atrperiod)

        # Entry/Exit engine state (lazy-activated when enter_trade/exit_trade is used)
        self._trade_seq: int = 0
        self._active_trade: Optional[BaseStrategy.TradeContext] = None
        self._trades_by_id: Dict[int, BaseStrategy.TradeContext] = {}
        self._trades_by_key: Dict[str, BaseStrategy.TradeContext] = {}
        self._banned_entry_key_bar_index: Set[int] = set()
        self._banned_exit_key_bar_index: Set[int] = set()

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

        # Auto signal processing (if enabled)
        if self.params.chainer_auto_signal:
            self._process_signals()

        # Drive entry/exit engine if a trade exists
        self._process_trade_engine()

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        tradeid = getattr(order, "tradeid", None)
        role = getattr(order, "info", {}).get(_ORDER_ROLE_KEY)

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
                    role = _ORDER_ROLE_ENTRY if is_entry else _ORDER_ROLE_EXIT

                if role == _ORDER_ROLE_ENTRY:
                    ctx.entry_price = float(order.executed.price)
                    ctx.status = BaseStrategy.TradeStatus.ACTIVE
                    if ctx.initial_stop_price is None:
                        ctx.initial_stop_price = float(ctx.key_kline_ref.low) if ctx.direction == "LONG" else float(ctx.key_kline_ref.high)
                    if ctx.stop_price is None:
                        ctx.stop_price = float(ctx.initial_stop_price)
                    ctx.breakeven_step = 0
                    self.log_info(
                        f"交易入场成交: trade_id={ctx.trade_id} key={ctx.key} direction={ctx.direction} entry_price={ctx.entry_price:.6f} "
                        f"stop_price={ctx.stop_price:.6f}"
                    )
                    self._place_or_replace_stop_order(ctx)
                    if ctx.risk_reward_ratio > 0.0:
                        tp_price = ChainerTraderLib.risk_reward_price(
                            ctx.direction,
                            float(ctx.entry_price),
                            float(ctx.initial_stop_price),
                            float(ctx.risk_reward_ratio),
                        )
                        if tp_price is not None:
                            ctx.tp_price = float(tp_price)
                            self.log_info(
                                f"创建止盈订单: trade_id={ctx.trade_id} key={ctx.key} direction={ctx.direction} "
                                f"tp={ctx.tp_price:.6f} rr={ctx.risk_reward_ratio:.6f}"
                            )
                            self._place_or_replace_tp_order(ctx)
                else:
                    ctx.exit_price = float(order.executed.price)
                    ctx.exit_value = float(order.executed.value)  # Store exit value for profit calculation
                    ctx.status = BaseStrategy.TradeStatus.CLOSED
                    if role == _ORDER_ROLE_STOP:
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

                    self._cancel_stop_order(ctx)
                    self._cancel_tp_order(ctx)
                    if self._active_trade is not None and self._active_trade.trade_id == ctx.trade_id:
                        self._active_trade = None
            elif order.status in [order.Canceled, order.Margin, order.Rejected]:
                status_name = (
                    "Canceled"
                    if order.status == order.Canceled
                    else "Margin"
                    if order.status == order.Margin
                    else "Rejected"
                )

                # Stop order cancellations are normal during stop replacement
                if role == _ORDER_ROLE_STOP:
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

                if role == _ORDER_ROLE_TP:
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

                if role == _ORDER_ROLE_ENTRY:
                    # Entry order did not fill -> cancel the trade context
                    ctx.status = BaseStrategy.TradeStatus.CANCELLED
                    ctx.cancel_reason = f"entry_order_{status_name.lower()}"
                    ctx.order = None
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
                        self._active_trade = None
                    return

                if role == _ORDER_ROLE_EXIT:
                    # Exit order failed -> keep trade active
                    ctx.status = BaseStrategy.TradeStatus.ACTIVE
                    ctx.order = None
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
        if self.params.log is None:
            cur_time = self.cur_datetime()
            print(f"[{cur_time}] {msg}")
            return
        cur_time = self.cur_datetime()
        self.params.log.info(
            f"[{cur_time}] {msg}, [{self.name()}][{self.bar_idx()}/{self.total_bars-1}]",
            LogTag.STRATEGY,
        )

    def log_debug(self, msg):
        if self.params.log is None:
            cur_time = self.cur_datetime()
            print(f"[{cur_time}] {msg}")
            return
        bars_info = ""
        if self.total_bars > 0:
            bars_info = f"[{self.bar_idx()}/{self.total_bars-1}]"
        cur_time = self.cur_datetime()
        self.params.log.debug(
            f"[{cur_time}] {msg}, [{self.name()}]{bars_info}",
            LogTag.STRATEGY,
        )

    def cur_datetime(self):
        return num2date(self.datas[0].datetime[0])

    def bar_idx(self):
        return len(self) - 1

    def _ensure_atr_indicator(self):
        if hasattr(self, "atr") and self.atr is not None:
            return
        self.atr = bt.indicators.ATR(self.datas[0], period=self.params.atrperiod)

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
        self._trade_seq += 1
        return self._trade_seq

    def _register_trade(self, ctx: "BaseStrategy.TradeContext") -> None:
        self._trades_by_id[ctx.trade_id] = ctx
        self._trades_by_key[ctx.key] = ctx

    def _cancel_stop_order(self, ctx: "BaseStrategy.TradeContext") -> None:
        so = getattr(ctx, "stop_order", None)
        if so is None:
            return
        try:
            if so.alive():
                self.cancel(so)
                return
        except Exception:
            pass
        ctx.stop_order = None

    def _cancel_tp_order(self, ctx: "BaseStrategy.TradeContext") -> None:
        to = getattr(ctx, "tp_order", None)
        if to is None:
            return
        try:
            if to.alive():
                self.cancel(to)
                return
        except Exception:
            pass
        ctx.tp_order = None

    def _place_or_replace_stop_order(self, ctx: "BaseStrategy.TradeContext") -> None:
        """
        Maintain a standing Stop order so stop-loss triggers on intrabar low/high.

        LONG  -> sell Stop at stop_price
        SHORT -> buy  Stop at stop_price
        """
        if ctx.stop_price is None:
            return

        close_size = float(abs(getattr(self.position, "size", 0.0)))
        if close_size <= 0.0:
            return

        self._cancel_stop_order(ctx)

        stop_price = float(ctx.stop_price)
        if ctx.direction == "LONG":
            so = super().sell(
                size=close_size,
                exectype=bt.Order.Stop,
                price=stop_price,
                tradeid=ctx.trade_id,
                **{_ORDER_ROLE_KEY: _ORDER_ROLE_STOP},
            )
        else:
            so = super().buy(
                size=close_size,
                exectype=bt.Order.Stop,
                price=stop_price,
                tradeid=ctx.trade_id,
                **{_ORDER_ROLE_KEY: _ORDER_ROLE_STOP},
            )
        ctx.stop_order = so

    def _place_or_replace_tp_order(self, ctx: "BaseStrategy.TradeContext") -> None:
        """
        Maintain a standing Limit order for take-profit when risk_reward_ratio > 0.

        LONG  -> sell Limit at tp_price
        SHORT -> buy  Limit at tp_price
        """
        if ctx.tp_price is None:
            return

        close_size = float(abs(getattr(self.position, "size", 0.0)))
        if close_size <= 0.0:
            return

        self._cancel_tp_order(ctx)

        tp_price = float(ctx.tp_price)
        if ctx.direction == "LONG":
            to = super().sell(
                size=close_size,
                exectype=bt.Order.Limit,
                price=tp_price,
                tradeid=ctx.trade_id,
                **{_ORDER_ROLE_KEY: _ORDER_ROLE_TP},
            )
        else:
            to = super().buy(
                size=close_size,
                exectype=bt.Order.Limit,
                price=tp_price,
                tradeid=ctx.trade_id,
                **{_ORDER_ROLE_KEY: _ORDER_ROLE_TP},
            )
        ctx.tp_order = to
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
        # Entry confirmation (independent of direction/mode, controlled by chainer_enter_need_confirm)
        if need_confirm is not None:
            entry_need_confirm = bool(need_confirm)
        else:
            entry_need_confirm = bool(self.params.chainer_enter_need_confirm)
        breakeven_on = bool(self.params.chainer_enable_breakeven if enable_breakeven is None else enable_breakeven)
        rr = float(self.params.chainer_risk_reward_ratio if risk_reward_ratio is None else risk_reward_ratio)
        # Exit confirmation (independent of direction/mode, controlled by chainer_exit_need_confirm)
        exit_need_confirm = bool(self.params.chainer_exit_need_confirm)

        ctx = BaseStrategy.TradeContext(
            trade_id=trade_id,
            key=key,
            direction=direction_norm,
            order=None,
            entry_key_bar_index=int(key_bar_index),
            key_kline_ref=key_ref,
            stoploss_atr_mult=sl_atr_mult,
            status=BaseStrategy.TradeStatus.PENDING_ENTRY_CONFIRM if entry_need_confirm else BaseStrategy.TradeStatus.OPENING,
            entry_need_confirm=entry_need_confirm,
            exit_need_confirm=exit_need_confirm,
            enable_breakeven=breakeven_on,
            risk_reward_ratio=rr,
            signal_metadata=dict(signal_metadata or {}),
        )

        if int(key_bar_index) in self._banned_entry_key_bar_index:
            ctx.status = BaseStrategy.TradeStatus.CANCELLED
            ctx.entry_key_banned = True
            ctx.cancel_reason = "entry_key_banned"
            self._register_trade(ctx)
            self.log_info(f"进场忽略(已禁用关键K): trade_id={ctx.trade_id} key={ctx.key} key_bar_index={int(key_bar_index)}")
            return ctx

        # Pre-compute stop based on key low (+ ATR adjustment if requested)
        stop_price = float(key_ref.low) if ctx.direction == "LONG" else float(key_ref.high)
        if sl_atr_mult != 0.0:
            self._ensure_atr_indicator()
            shift = int(key_bar_index) - self.bar_idx()
            # ATR needs atrperiod bars to calculate, so we need to safely access it
            atr_val = 0.0
            if self.atr is not None:
                # Try to get ATR value at shift position, fallback to current bar or 0.0
                for attempt_shift in [shift, 0]:
                    try:
                        val = self.atr[attempt_shift]
                        # Check if value is valid (not None, not NaN, not Inf)
                        if val is not None:
                            val_float = float(val)
                            if not (math.isnan(val_float) or math.isinf(val_float)):
                                atr_val = val_float
                                break
                    except (IndexError, TypeError, ValueError):
                        continue
            if ctx.direction == "LONG":
                stop_price = float(key_ref.low) - (sl_atr_mult * atr_val)
            else:
                stop_price = float(key_ref.high) + (sl_atr_mult * atr_val)
        suggested_stop_price = ctx.signal_metadata.get("suggested_stop_price")
        if suggested_stop_price is not None:
            stop_price = float(suggested_stop_price)
        ctx.initial_stop_price = stop_price
        ctx.stop_price = stop_price

        self._register_trade(ctx)
        self._active_trade = ctx

        self.log_info(
            f"创建交易(进场): trade_id={ctx.trade_id} key={ctx.key} direction={ctx.direction} need_confirm={1 if ctx.entry_need_confirm else 0} "
            f"key_time={ctx.key_kline_ref.dt} key_high={ctx.key_kline_ref.high:.6f} key_low={ctx.key_kline_ref.low:.6f} "
            f"stop_price={ctx.stop_price:.6f} sl_atr_mult={ctx.stoploss_atr_mult:.6f} rr={ctx.risk_reward_ratio:.6f} "
            f"breakeven={1 if ctx.enable_breakeven else 0}"
        )

        if not ctx.entry_need_confirm:
            order = (
                self.buy(tradeid=ctx.trade_id, **{_ORDER_ROLE_KEY: _ORDER_ROLE_ENTRY})
                if ctx.direction == "LONG"
                else self.sell(tradeid=ctx.trade_id, **{_ORDER_ROLE_KEY: _ORDER_ROLE_ENTRY})
            )
            ctx.order = order
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
            exit_need_confirm = bool(self.params.chainer_exit_need_confirm)
        exit_key_ref = self._kline_ref_by_bar_index(key_bar_index)
        ctx.exit_need_confirm = exit_need_confirm
        ctx.exit_key_bar_index = int(key_bar_index)
        ctx.exit_key_kline_ref = exit_key_ref

        if int(key_bar_index) in self._banned_exit_key_bar_index:
            ctx.exit_key_banned = True
            self.log_info(f"出场忽略(已禁用关键K): trade_id={ctx.trade_id} key={ctx.key} key_bar_index={int(key_bar_index)}")
            return ctx

        self.log_info(
            f"请求出场: trade_id={ctx.trade_id} key={ctx.key} need_confirm={1 if exit_need_confirm else 0} "
            f"key_time={exit_key_ref.dt} key_high={exit_key_ref.high:.6f} key_low={exit_key_ref.low:.6f}"
        )

        if not exit_need_confirm:
            oco_order = ctx.stop_order if ctx.stop_order is not None and ctx.tp_order is None else None
            if oco_order is None:
                self._cancel_stop_order(ctx)
            self._cancel_tp_order(ctx)
            close_size = float(abs(getattr(self.position, "size", 0.0)))
            if close_size <= 0.0:
                self.log_info(f"创建卖出订单失败(无持仓): trade_id={ctx.trade_id} key={ctx.key}")
                return ctx
            pos_size = float(getattr(self.position, "size", 0.0))
            order = (
                self.sell(size=close_size, tradeid=ctx.trade_id, oco=oco_order, **{_ORDER_ROLE_KEY: _ORDER_ROLE_EXIT})
                if pos_size > 0
                else self.buy(size=close_size, tradeid=ctx.trade_id, oco=oco_order, **{_ORDER_ROLE_KEY: _ORDER_ROLE_EXIT})
            )
            if order is None:
                self.log_info(f"创建平仓订单失败: trade_id={ctx.trade_id} key={ctx.key}")
                return ctx
            ctx.order = order
            self.order = order
            ctx.status = BaseStrategy.TradeStatus.CLOSING
            self.log_info(f"创建平仓订单: trade_id={ctx.trade_id} key={ctx.key} size={close_size}")
        else:
            ctx.status = BaseStrategy.TradeStatus.PENDING_EXIT_CONFIRM

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

    def _process_signals(self) -> None:
        """
        Process long/short signals based on trading mode.

        Mode-based signal processing (reference: Pine Script ChainerTrader v3):
        - LONG_ONLY: long signal opens long, short signal closes long
        - SHORT_ONLY: short signal opens short, long signal closes short
        - BOTH: long signal opens long, short signal opens short, exit via stop/breakeven/TP
        """
        # Get signals from subclass (fixed semantics)
        long_signal = self.get_long_signal()
        short_signal = self.get_short_signal()

        # Check whether new entries are allowed based on equity protection
        can_open_new_position = self._can_open_new_position()

        # Determine trading mode
        mode = str(self.params.chainer_mode).upper()
        if mode not in ("LONG_ONLY", "SHORT_ONLY", "BOTH"):
            mode = "LONG_ONLY"
        
        # Debug log when signals are triggered
        if long_signal or short_signal:
            self.log_debug(f"信号触发: mode={mode} long_signal={long_signal} short_signal={short_signal}")

        # Check current state
        no_active_trade = self._active_trade is None or self._active_trade.status in (
            BaseStrategy.TradeStatus.CLOSED,
            BaseStrategy.TradeStatus.CANCELLED,
        )
        pos_size = float(getattr(self.position, "size", 0.0))
        has_long_position = pos_size > 0.0
        has_short_position = pos_size < 0.0
        trade_is_active = (
            self._active_trade is not None
            and self._active_trade.status == BaseStrategy.TradeStatus.ACTIVE
        )

        if mode == "LONG_ONLY":
            # Long signal opens long
            if long_signal and no_active_trade and can_open_new_position:
                self.log_info(f"LONG_ONLY模式: 检测到做多信号，尝试开多仓")
                try:
                    self.enter_trade(
                        direction="LONG",
                        key_bar_index=self.bar_idx(),
                        signal_metadata=self.get_long_signal_context(),
                    )
                except (ValueError, RuntimeError) as e:
                    self.log_debug(f"_process_signals: enter_trade LONG failed: {e}")

            # Short signal closes long
            if short_signal and trade_is_active and has_long_position:
                self.log_info(f"LONG_ONLY模式: 检测到做空信号，尝试平多仓")
                try:
                    self.exit_trade(key_bar_index=self.bar_idx())
                except (ValueError, RuntimeError) as e:
                    self.log_debug(f"_process_signals: exit_trade failed: {e}")

        elif mode == "SHORT_ONLY":
            # Short signal opens short
            if short_signal and no_active_trade and can_open_new_position:
                self.log_info(f"SHORT_ONLY模式: 检测到做空信号，尝试开空仓")
                try:
                    self.enter_trade(
                        direction="SHORT",
                        key_bar_index=self.bar_idx(),
                        signal_metadata=self.get_short_signal_context(),
                    )
                except (ValueError, RuntimeError) as e:
                    self.log_debug(f"_process_signals: enter_trade SHORT failed: {e}")

            # Long signal closes short
            if long_signal and trade_is_active and has_short_position:
                self.log_info(f"SHORT_ONLY模式: 检测到做多信号，尝试平空仓")
                try:
                    self.exit_trade(key_bar_index=self.bar_idx())
                except (ValueError, RuntimeError) as e:
                    self.log_debug(f"_process_signals: exit_trade failed: {e}")

        elif mode == "BOTH":
            # Long signal opens long
            if long_signal and no_active_trade and can_open_new_position:
                try:
                    self.enter_trade(
                        direction="LONG",
                        key_bar_index=self.bar_idx(),
                        signal_metadata=self.get_long_signal_context(),
                    )
                except (ValueError, RuntimeError) as e:
                    self.log_debug(f"_process_signals: enter_trade LONG failed: {e}")

            # Short signal opens short
            if short_signal and no_active_trade and can_open_new_position:
                try:
                    self.enter_trade(
                        direction="SHORT",
                        key_bar_index=self.bar_idx(),
                        signal_metadata=self.get_short_signal_context(),
                    )
                except (ValueError, RuntimeError) as e:
                    self.log_debug(f"_process_signals: enter_trade SHORT failed: {e}")
            # In BOTH mode, exit is handled by stop/breakeven/take-profit mechanisms only

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
            long_signal = self.get_long_signal()
            short_signal = self.get_short_signal()
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
                ctx.status = BaseStrategy.TradeStatus.CANCELLED
                ctx.cancel_reason = "entry_pending_exit_signal"
                self._banned_entry_key_bar_index.add(int(ctx.entry_key_bar_index))
                if ctx.direction == "LONG":
                    self.log_info(
                        f"进场取消(未确认前出现出场信号): trade_id={ctx.trade_id} key={ctx.key} close={close:.6f}"
                    )
                else:
                    self.log_info(
                        f"进场取消(未确认前出现出场信号): trade_id={ctx.trade_id} key={ctx.key} close={close:.6f}"
                    )
                self._active_trade = None
                return

            # If equity protection is enabled and current equity is below threshold,
            # cancel the pending entry as if confirmation failed.
            if not self._can_open_new_position():
                ctx.status = BaseStrategy.TradeStatus.CANCELLED
                ctx.cancel_reason = "entry_equity_below_min"
                self._banned_entry_key_bar_index.add(int(ctx.entry_key_bar_index))
                self.log_info(
                    f"进场取消(账户净值低于最小进场阈值): trade_id={ctx.trade_id} key={ctx.key} close={close:.6f}"
                )
                self._active_trade = None
                return

            if confirm_ok:
                order = (
                    self.buy(tradeid=ctx.trade_id, **{_ORDER_ROLE_KEY: _ORDER_ROLE_ENTRY})
                    if ctx.direction == "LONG"
                    else self.sell(tradeid=ctx.trade_id, **{_ORDER_ROLE_KEY: _ORDER_ROLE_ENTRY})
                )
                ctx.order = order
                self.order = order
                ctx.status = BaseStrategy.TradeStatus.OPENING
                if ctx.direction == "LONG":
                    self.log_info(f"进场确认成功: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f} > key_high")
                    self.log_info(f"创建买入订单: trade_id={ctx.trade_id} key={ctx.key}")
                    self.log_info("下单时机: 本K线收盘确认后提交市价单，默认在下一根K线开盘成交")
                else:
                    self.log_info(f"进场确认成功: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f} < key_low")
                    self.log_info(f"创建卖出订单(开空): trade_id={ctx.trade_id} key={ctx.key}")
                    self.log_info("下单时机: 本K线收盘确认后提交市价单，默认在下一根K线开盘成交")
            elif confirm_fail:
                ctx.status = BaseStrategy.TradeStatus.CANCELLED
                ctx.cancel_reason = "entry_confirm_failed"
                self._banned_entry_key_bar_index.add(int(ctx.entry_key_bar_index))
                if ctx.direction == "LONG":
                    self.log_info(f"进场确认失败: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f} < key_low")
                else:
                    self.log_info(f"进场确认失败: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f} > key_high")
                self._active_trade = None
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
                    self._cancel_stop_order(ctx)
                self._cancel_tp_order(ctx)
                close_size = float(abs(getattr(self.position, "size", 0.0)))
                if close_size <= 0.0:
                    self.log_info(f"创建卖出订单失败(无持仓): trade_id={ctx.trade_id} key={ctx.key}")
                    return
                pos_size = float(getattr(self.position, "size", 0.0))
                order = (
                    self.sell(size=close_size, tradeid=ctx.trade_id, oco=oco_order, **{_ORDER_ROLE_KEY: _ORDER_ROLE_EXIT})
                    if pos_size > 0
                    else self.buy(size=close_size, tradeid=ctx.trade_id, oco=oco_order, **{_ORDER_ROLE_KEY: _ORDER_ROLE_EXIT})
                )
                if order is None:
                    self.log_info(f"创建平仓订单失败: trade_id={ctx.trade_id} key={ctx.key}")
                    return
                ctx.order = order
                self.order = order
                ctx.status = BaseStrategy.TradeStatus.CLOSING
                if ctx.direction == "LONG":
                    self.log_info(f"出场确认成功: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f} < key_low")
                else:
                    self.log_info(f"出场确认成功: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f} > key_high")
                self.log_info(f"创建平仓订单: trade_id={ctx.trade_id} key={ctx.key} size={close_size}")
            elif confirm_fail:
                ctx.status = BaseStrategy.TradeStatus.ACTIVE
                ctx.exit_key_banned = True
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

        # Breakeven management (R ladder):
        # - Define base risk R = LONG: entry - initial_stop; SHORT: initial_stop - entry
        # - When profit reaches n*R (n>=1), move stop to (n-1)*R from entry
        #   LONG: stop = entry + (n-1)*R
        #   SHORT: stop = entry - (n-1)*R
        # - breakeven_step is set to the reached R level n (not "number of updates"),
        #   so it remains correct even if price jumps multiple R levels in a single bar.
        if ctx.enable_breakeven:
            entry_price = float(ctx.entry_price)
            initial_stop = float(ctx.initial_stop_price)
            is_long = ctx.direction == "LONG"

            risk = (entry_price - initial_stop) if is_long else (initial_stop - entry_price)
            if risk > 0.0:
                close = float(self.data.close[0])
                new_stop = ChainerTraderLib.breakeven_price(
                    ctx.direction,
                    entry_price,
                    initial_stop,
                    close,
                )
                if new_stop is not None:
                    should_update = (new_stop > float(ctx.stop_price)) if is_long else (new_stop < float(ctx.stop_price))
                    if should_update:
                        # Derive reached R-level n from the returned stop:
                        # LONG: (stop-entry)/risk = n-1; SHORT: (entry-stop)/risk = n-1
                        level = ((new_stop - entry_price) / risk) if is_long else ((entry_price - new_stop) / risk)
                        n = int(math.floor(level + _BREAKEVEN_EPS)) + 1

                        ctx.stop_price = float(new_stop)
                        ctx.breakeven_step = max(int(ctx.breakeven_step), int(n))
                        self.log_info(
                            f"保本移动止损: trade_id={ctx.trade_id} key={ctx.key} direction={ctx.direction} "
                            f"step={ctx.breakeven_step} stop={ctx.stop_price:.6f}"
                        )
                        self._place_or_replace_stop_order(ctx)

        # Ensure a standing stop exists during ACTIVE trade (covers cases where the stop
        # order was cancelled externally or not created due to sizing issues).
        if ctx.stop_price is not None and (ctx.stop_order is None or not getattr(ctx.stop_order, "alive", lambda: False)()):
            self._place_or_replace_stop_order(ctx)

        # Ensure a standing TP exists during ACTIVE trade when enabled.
        if ctx.tp_price is not None and (ctx.tp_order is None or not getattr(ctx.tp_order, "alive", lambda: False)()):
            self._place_or_replace_tp_order(ctx)

    def need_stop_loss(self):
        if not self.params.stoploss:
            return False

        if self.data.close[0] < self.stopLossPoint:
            return True
        return False

    def update_stop_loss_point(self):
        if not self.params.stoploss:
            return

        pdist = 0
        if self.params.atr:
            pdist = self.atr[0] * self.params.atrdist
        self.stopLossPoint = self.datas[0].close[0] - pdist

    def need_takeprofit(self):
        if not self.params.takeprofit:
            return False

        if self.data.close[0] > self.takeProfitPoint:
            return True
        return False

    def update_takeprofit_point(self):
        if not self.params.takeprofit:
            return

        pdist = 0
        if self.params.atr:
            pdist = self.atr[0] * self.params.atrdist
        self.takeProfitPoint = self.datas[0].close[0] + pdist

    def name(self):
        return self.params.name

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
