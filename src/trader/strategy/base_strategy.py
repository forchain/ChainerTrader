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
from trader.utils.trend import TrendType


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
        ("chainer_allow_short", True),
        ("chainer_direction", "LONG"),  # LONG or SHORT
        ("chainer_auto_signal", False),  # Enable auto signal processing via get_entry_signal/get_exit_signal
        # Entry/Exit engine defaults (can be overridden per call)
        ("chainer_stoploss_atr_mult", 0.0),
        ("chainer_entry_need_confirm", True),
        ("chainer_exit_need_confirm", True),
        ("chainer_enable_breakeven", True),
        ("chainer_risk_reward_ratio", 0.0),
    )

    class TradeStatus(str, Enum):
        PENDING_ENTRY_CONFIRM = "pending_entry_confirm"
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

        initial_stop_price: Optional[float] = None
        stop_price: Optional[float] = None
        breakeven_step: int = 0

        entry_key_banned: bool = False
        exit_key_banned: bool = False
        exit_key_bar_index: Optional[int] = None
        exit_key_kline_ref: Optional["BaseStrategy.KlineRef"] = None

        cancel_reason: Optional[str] = None

    def __init__(self):
        super().__init__()
        self.order = None

        # Stop loss point
        if self.params.stoploss:
            self.stopLossPoint = 0

        # take profit
        if self.params.takeprofit:
            self.takeProfitPoint = 0

        # To set the stop price
        if self.params.atr:
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

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log_info(f"买入, 价格: {order.executed.price:.2f}, 花费: {order.executed.value:.2f}, 手续费: {order.executed.comm:.2f}")

            else:  # Sell
                self.log_info(f"卖出, 价格: {order.executed.price:.2f}, 花费: {order.executed.value:.2f}, 手续费: {order.executed.comm:.2f}")

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log_info("Order Canceled/Margin/Rejected")

        self.order = None

        # Sync entry/exit engine state with order completion (by tradeid)
        try:
            tradeid = getattr(order, "tradeid", None)
            if tradeid is None:
                return
            ctx = self._trades_by_id.get(int(tradeid))
            if ctx is None:
                return

            if order.status in [order.Completed]:
                is_entry = order.isbuy() if ctx.direction == "LONG" else order.issell()
                if is_entry:
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
                else:
                    ctx.exit_price = float(order.executed.price)
                    ctx.status = BaseStrategy.TradeStatus.CLOSED
                    self.log_info(f"交易出场成交: trade_id={ctx.trade_id} key={ctx.key} direction={ctx.direction} exit_price={ctx.exit_price:.6f}")
                    if self._active_trade is not None and self._active_trade.trade_id == ctx.trade_id:
                        self._active_trade = None
        except Exception as e:
            self.log_debug(f"notify_order: trade sync failed: {e}")

    def notify_trade(self, trade):
        if not trade.isclosed:
            return

        self.log_info(f"营业利润, 毛利润: {trade.pnl:.2f}, 净利润: {trade.pnlcomm:.2f}")

    def log_info(self, msg):
        if self.params.log is None:
            print(msg)
            return
        self.params.log.info(f"{msg}, [{self.name()}][{self.bar_idx()}/{self.total_bars-1}]", LogTag.STRATEGY)

    def log_debug(self, msg):
        if self.params.log is None:
            print(msg)
            return
        bars_info = ""
        if self.total_bars > 0:
            bars_info = f"[{self.bar_idx()}/{self.total_bars-1}]"
        self.params.log.debug(f"{msg}, [{self.name()}]{bars_info}", LogTag.STRATEGY)

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

    def enter_trade(
        self,
        trade_key: Any = None,
        direction: str = "LONG",
        key_bar_index: int = 0,
        stoploss_atr_mult: Optional[float] = None,
        need_confirm: Optional[bool] = None,
        enable_breakeven: Optional[bool] = None,
        risk_reward_ratio: Optional[float] = None,
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
        if direction_norm == "SHORT" and not bool(self.params.chainer_allow_short):
            raise ValueError("SHORT is disabled by chainer_allow_short")

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
        entry_need_confirm = bool(self.params.chainer_entry_need_confirm if need_confirm is None else need_confirm)
        breakeven_on = bool(self.params.chainer_enable_breakeven if enable_breakeven is None else enable_breakeven)
        rr = float(self.params.chainer_risk_reward_ratio if risk_reward_ratio is None else risk_reward_ratio)
        exit_need_confirm = bool(self.params.chainer_exit_need_confirm)

        ctx = BaseStrategy.TradeContext(
            trade_id=trade_id,
            key=key,
            direction=direction_norm,
            order=None,
            entry_key_bar_index=int(key_bar_index),
            key_kline_ref=key_ref,
            stoploss_atr_mult=sl_atr_mult,
            status=BaseStrategy.TradeStatus.PENDING_ENTRY_CONFIRM if entry_need_confirm else BaseStrategy.TradeStatus.ACTIVE,
            entry_need_confirm=entry_need_confirm,
            exit_need_confirm=exit_need_confirm,
            enable_breakeven=breakeven_on,
            risk_reward_ratio=rr,
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
            order = self.buy(tradeid=ctx.trade_id) if ctx.direction == "LONG" else self.sell(tradeid=ctx.trade_id)
            ctx.order = order
            self.order = order
            if ctx.direction == "LONG":
                self.log_info(f"创建买入订单: trade_id={ctx.trade_id} key={ctx.key}")
            else:
                self.log_info(f"创建卖出订单(开空): trade_id={ctx.trade_id} key={ctx.key}")

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

        exit_need_confirm = bool(self.params.chainer_exit_need_confirm if need_confirm is None else need_confirm)
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
            close_size = int(abs(getattr(self.position, "size", 0)))
            if close_size <= 0:
                self.log_info(f"创建卖出订单失败(无持仓): trade_id={ctx.trade_id} key={ctx.key}")
                return ctx
            pos_size = int(getattr(self.position, "size", 0))
            order = self.sell(size=close_size, tradeid=ctx.trade_id) if pos_size > 0 else self.buy(size=close_size, tradeid=ctx.trade_id)
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

    def get_entry_signal(self) -> bool:
        """
        Override in subclass to generate entry signal.

        Returns:
            bool: True when entry condition is met (e.g., golden cross for LONG).
        """
        return False

    def get_exit_signal(self) -> bool:
        """
        Override in subclass to generate exit signal.

        Returns:
            bool: True when exit condition is met (e.g., death cross for LONG).
        """
        return False

    def _process_signals(self) -> None:
        """
        Process entry/exit signals based on direction.

        Direction-aware signal processing (reference: Pine Script ChainerTrader):
        - LONG direction: entry signal triggers enter_trade, exit signal triggers exit_trade
        - SHORT direction (if allowed): exit signal triggers enter_trade, entry signal triggers exit_trade
        """
        # Get raw signals from subclass
        entry_signal_raw = self.get_entry_signal()
        exit_signal_raw = self.get_exit_signal()

        # Determine effective direction
        direction = str(self.params.chainer_direction).upper()
        if direction not in ("LONG", "SHORT"):
            direction = "LONG"
        if direction == "SHORT" and not bool(self.params.chainer_allow_short):
            direction = "LONG"

        # Direction-aware signal mapping
        dir_is_long = direction == "LONG"
        can_use_short_dir = bool(self.params.chainer_allow_short) and not dir_is_long

        if dir_is_long:
            effective_entry_signal = entry_signal_raw
            effective_exit_signal = exit_signal_raw
        elif can_use_short_dir:
            # SHORT direction: swap signals
            effective_entry_signal = exit_signal_raw
            effective_exit_signal = entry_signal_raw
        else:
            # SHORT not allowed but direction is SHORT: no signals
            effective_entry_signal = False
            effective_exit_signal = False

        # Process entry signal
        if effective_entry_signal:
            # Check if no active trade or current trade is closed/cancelled
            if self._active_trade is None or self._active_trade.status in (
                BaseStrategy.TradeStatus.CLOSED,
                BaseStrategy.TradeStatus.CANCELLED,
            ):
                try:
                    self.enter_trade(
                        direction=direction,
                        key_bar_index=self.bar_idx(),
                    )
                except (ValueError, RuntimeError) as e:
                    self.log_debug(f"_process_signals: enter_trade failed: {e}")

        # Process exit signal
        if effective_exit_signal:
            # Check if there's an active trade that can be exited
            if self._active_trade is not None and self._active_trade.status in (
                BaseStrategy.TradeStatus.ACTIVE,
                BaseStrategy.TradeStatus.PENDING_ENTRY_CONFIRM,
            ):
                try:
                    self.exit_trade(key_bar_index=self.bar_idx())
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
            if confirm_ok:
                order = self.buy(tradeid=ctx.trade_id) if ctx.direction == "LONG" else self.sell(tradeid=ctx.trade_id)
                ctx.order = order
                self.order = order
                ctx.status = BaseStrategy.TradeStatus.ACTIVE
                if ctx.direction == "LONG":
                    self.log_info(f"进场确认成功: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f} > key_high")
                    self.log_info(f"创建买入订单: trade_id={ctx.trade_id} key={ctx.key}")
                else:
                    self.log_info(f"进场确认成功: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f} < key_low")
                    self.log_info(f"创建卖出订单(开空): trade_id={ctx.trade_id} key={ctx.key}")
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
                close_size = int(abs(getattr(self.position, "size", 0)))
                if close_size <= 0:
                    self.log_info(f"创建卖出订单失败(无持仓): trade_id={ctx.trade_id} key={ctx.key}")
                    return
                pos_size = int(getattr(self.position, "size", 0))
                order = self.sell(size=close_size, tradeid=ctx.trade_id) if pos_size > 0 else self.buy(size=close_size, tradeid=ctx.trade_id)
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

        # Breakeven ladder
        if ctx.enable_breakeven and ctx.risk_reward_ratio > 0.0:
            entry_price = float(ctx.entry_price)
            initial_stop = float(ctx.initial_stop_price)
            risk = entry_price - initial_stop if ctx.direction == "LONG" else initial_stop - entry_price
            if risk > 0:
                close = float(self.data.close[0])
                rr = float(ctx.risk_reward_ratio)
                if ctx.direction == "LONG":
                    while close >= float(ctx.entry_price) + ((ctx.breakeven_step + 1) * rr * risk):
                        ctx.breakeven_step += 1
                        new_stop = float(ctx.entry_price) + ((ctx.breakeven_step - 1) * rr * risk)
                        if new_stop > float(ctx.stop_price):
                            ctx.stop_price = new_stop
                            self.log_info(
                                f"保本移动止损: trade_id={ctx.trade_id} key={ctx.key} direction=LONG step={ctx.breakeven_step} "
                                f"stop={ctx.stop_price:.6f}"
                            )
                else:
                    while close <= float(ctx.entry_price) - ((ctx.breakeven_step + 1) * rr * risk):
                        ctx.breakeven_step += 1
                        new_stop = float(ctx.entry_price) - ((ctx.breakeven_step - 1) * rr * risk)
                        if new_stop < float(ctx.stop_price):
                            ctx.stop_price = new_stop
                            self.log_info(
                                f"保本移动止损: trade_id={ctx.trade_id} key={ctx.key} direction=SHORT step={ctx.breakeven_step} "
                                f"stop={ctx.stop_price:.6f}"
                            )

        # Bar-by-bar stop check (market exit)
        close = float(self.data.close[0])
        stop_hit = close <= float(ctx.stop_price) if ctx.direction == "LONG" else close >= float(ctx.stop_price)
        if stop_hit and self.order is None:
            close_size = int(abs(getattr(self.position, "size", 0)))
            if close_size <= 0:
                self.log_info(f"触发止损但无持仓: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f}")
                return
            pos_size = int(getattr(self.position, "size", 0))
            order = self.sell(size=close_size, tradeid=ctx.trade_id) if pos_size > 0 else self.buy(size=close_size, tradeid=ctx.trade_id)
            if order is None:
                self.log_info(f"触发止损但创建卖出订单失败: trade_id={ctx.trade_id} key={ctx.key} close={close:.6f}")
                return
            ctx.order = order
            self.order = order
            ctx.status = BaseStrategy.TradeStatus.CLOSING
            self.log_info(
                f"触发止损出场: trade_id={ctx.trade_id} key={ctx.key} direction={ctx.direction} close={close:.6f} "
                f"stop={float(ctx.stop_price):.6f} size={close_size}"
            )

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
            int: Calculated position size (number of units)
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
        
        return int(size) if size > 0 else 0

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