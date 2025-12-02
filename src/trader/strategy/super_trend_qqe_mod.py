"""
SuperTrend + QQE MOD + Trend A Strategy

A multi-indicator strategy combining:
- SuperTrend: Trend direction and dynamic stop loss levels
- Trend A: Heikin Ashi based trend confirmation
- QQE MOD: Momentum confirmation signals

Entry/Exit Logic:
- Long: SuperTrend Up + TrendA Green + QQE Up Signal
- Short: SuperTrend Down + TrendA Red + QQE Down Signal
- Stop Loss: SuperTrend band (up for long, dn for short)
- Take Profit: 2x stop loss distance
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import math

from trader.indicators.qqe_mod import QQEMod
from trader.indicators.super_trend import SuperTrend
from trader.indicators.trend_a import TrendA
from trader.strategy.base_strategy import BaseStrategy
from trader.utils.ma import MAType


class SuperTrendQQEMODStrategy(BaseStrategy):
    """
    SuperTrend + QQE MOD + Trend A combined strategy.

    Uses three indicators to confirm entry signals and SuperTrend bands
    for dynamic stop loss with 2:1 risk-reward ratio.
    """

    params = (
        ("name", "SuperTrendQQEMOD"),
        # Super Trend parameters
        ("st_periods", 10),
        ("st_multiplier", 3.3),
        # Trend A parameters
        ("ta_ma_type", MAType.EMA),
        ("ta_ma_period", 77),
        ("ta_ma_period_smoothing", 21),
        # QQE MOD parameters
        ("qqe_rsi_length_secondary", 10),
        # Risk management
        ("risk_reward_ratio", 2.0),
        # Debug mode
        ("debug", True),
    )

    def __init__(self):
        super().__init__()

        # Initialize indicators
        self.super_trend = SuperTrend(
            self.data,
            periods=self.params.st_periods,
            multiplier=self.params.st_multiplier,
        )

        self.trend_a = TrendA(
            self.data,
            ma_type=self.params.ta_ma_type,
            ma_period=self.params.ta_ma_period,
            ma_period_smoothing=self.params.ta_ma_period_smoothing,
        )

        self.qqe_mod = QQEMod(
            self.data,
            rsi_length_secondary=self.params.qqe_rsi_length_secondary,
        )

        # Order tracking
        self.order = None
        self.entry_price = None
        self.stop_loss_price = None
        self.take_profit_price = None
        self.position_type = None  # 'long' or 'short'

        # Track if we already traded in current Trend A direction
        # Only allow one trade per Trend A direction
        self.traded_in_long_trend = False   # True if we traded while ta_trend > 0
        self.traded_in_short_trend = False  # True if we traded while ta_trend < 0
        self.last_ta_trend_direction = 0    # Track Trend A direction changes

    def _get_datetime_str(self):
        """Get current bar datetime as string."""
        return self.data.datetime.datetime(0).strftime("%Y-%m-%d %H:%M")

    def _debug(self, msg):
        """Print debug message if debug mode is enabled."""
        if self.params.debug:
            dt_str = self._get_datetime_str()
            self.log_info(f"[DEBUG][{dt_str}] {msg}")

    def next(self):
        """Main strategy logic executed on each bar."""
        super().next()

        # Skip if order is pending (Rule 2: only enter when no pending order)
        if self.order:
            self._debug("Skipping - order pending")
            return

        # Get current indicator values
        st_trend = self.super_trend.trend[0]
        st_up = self.super_trend.up[0]
        st_dn = self.super_trend.dn[0]
        ta_trend = self.trend_a.trend[0]
        ta_open = self.trend_a.open_line[0]
        ta_close = self.trend_a.close_line[0]
        qqe_up = self.qqe_mod.qqe_up_signal[0]
        qqe_down = self.qqe_mod.qqe_down_signal[0]
        qqe_sec_rsi = self.qqe_mod.secondary_rsi_histogram[0]

        # OHLC data
        bar_o, bar_h, bar_l, bar_c = self.data.open[0], self.data.high[0], self.data.low[0], self.data.close[0]

        # Determine current Trend A direction
        current_ta_direction = 1 if ta_trend > 0 else (-1 if ta_trend < 0 else 0)

        # Rule 3: Reset trade flag when Trend A direction changes
        if current_ta_direction != self.last_ta_trend_direction:
            old_dir = self.last_ta_trend_direction
            if current_ta_direction == 1:
                # Trend A turned green - reset long trade flag
                self.traded_in_long_trend = False
                self._debug(f"TrendA direction changed: {old_dir} -> 1 (GREEN), reset traded_in_long_trend=False")
            elif current_ta_direction == -1:
                # Trend A turned red - reset short trade flag
                self.traded_in_short_trend = False
                self._debug(f"TrendA direction changed: {old_dir} -> -1 (RED), reset traded_in_short_trend=False")
            else:
                self._debug(f"TrendA direction changed: {old_dir} -> 0 (NEUTRAL)")
            self.last_ta_trend_direction = current_ta_direction

        # Entry condition components for debugging
        st_long_cond = st_trend == 1
        ta_long_cond = ta_trend > 0
        qqe_long_cond = not math.isnan(qqe_up)
        not_traded_long = not self.traded_in_long_trend

        st_short_cond = st_trend == -1
        ta_short_cond = ta_trend < 0
        qqe_short_cond = not math.isnan(qqe_down)
        not_traded_short = not self.traded_in_short_trend

        # Entry conditions with Rule 3: one trade per Trend A direction
        is_long_entry = st_long_cond and ta_long_cond and qqe_long_cond and not_traded_long
        is_short_entry = st_short_cond and ta_short_cond and qqe_short_cond and not_traded_short

        # Log indicator values on every bar when any condition is partially met
        if st_long_cond or st_short_cond or ta_long_cond or ta_short_cond:
            self._debug(
                f"OHLC: O={bar_o:.2f} H={bar_h:.2f} L={bar_l:.2f} C={bar_c:.2f} | "
                f"ST: trend={st_trend} up={st_up:.2f} dn={st_dn:.2f} | "
                f"TA: trend={ta_trend:.4f} open={ta_open:.2f} close={ta_close:.2f} dir={current_ta_direction} | "
                f"QQE: up={qqe_up:.4f} down={qqe_down:.4f} sec_rsi={qqe_sec_rsi:.4f}"
            )

        # Log entry condition evaluation
        if is_long_entry or is_short_entry:
            self._debug(
                f"ENTRY CONDITIONS MET | "
                f"LONG: ST={st_long_cond} TA={ta_long_cond} QQE={qqe_long_cond} NotTraded={not_traded_long} => {is_long_entry} | "
                f"SHORT: ST={st_short_cond} TA={ta_short_cond} QQE={qqe_short_cond} NotTraded={not_traded_short} => {is_short_entry}"
            )

        # Position management
        if not self.position:
            # No position - check for entry
            if is_long_entry:
                self._debug(
                    f"ATTEMPTING LONG ENTRY | "
                    f"ST: trend={st_trend} up={st_up:.2f} | "
                    f"TA: trend={ta_trend:.4f} | "
                    f"QQE: up_signal={qqe_up:.4f} | "
                    f"traded_in_long_trend={self.traded_in_long_trend}"
                )
                self._enter_long(st_up)
            elif is_short_entry:
                self._debug(
                    f"ATTEMPTING SHORT ENTRY | "
                    f"ST: trend={st_trend} dn={st_dn:.2f} | "
                    f"TA: trend={ta_trend:.4f} | "
                    f"QQE: down_signal={qqe_down:.4f} | "
                    f"traded_in_short_trend={self.traded_in_short_trend}"
                )
                self._enter_short(st_dn)
        else:
            # Have position - check for exit
            self._check_exit()

    def _enter_long(self, stop_loss_level):
        """Enter long position with stop loss and take profit."""
        current_price = self.data.close[0]
        dt_str = self._get_datetime_str()

        # Skip if stop loss level is invalid
        if math.isnan(stop_loss_level):
            self._debug("LONG ENTRY SKIPPED - stop_loss_level is NaN")
            return
        if stop_loss_level >= current_price:
            self._debug(
                f"LONG ENTRY SKIPPED - invalid SL: stop_loss_level={stop_loss_level:.2f} >= current_price={current_price:.2f}"
            )
            return

        self.stop_loss_price = stop_loss_level
        stop_distance = current_price - stop_loss_level
        self.take_profit_price = current_price + self.params.risk_reward_ratio * stop_distance
        self.position_type = 'long'

        self.log_info(
            f">>> LONG ENTRY [{dt_str}] | "
            f"Price={current_price:.2f} | "
            f"SL={self.stop_loss_price:.2f} (dist={stop_distance:.2f}) | "
            f"TP={self.take_profit_price:.2f} (dist={self.take_profit_price - current_price:.2f}) | "
            f"RR={self.params.risk_reward_ratio}"
        )

        self.order = self.buy()
        self.traded_in_long_trend = True  # Mark as traded in this green Trend A phase
        self._debug("Set traded_in_long_trend=True")

    def _enter_short(self, stop_loss_level):
        """Enter short position with stop loss and take profit."""
        current_price = self.data.close[0]
        dt_str = self._get_datetime_str()

        # Skip if stop loss level is invalid
        if math.isnan(stop_loss_level):
            self._debug("SHORT ENTRY SKIPPED - stop_loss_level is NaN")
            return
        if stop_loss_level <= current_price:
            self._debug(
                f"SHORT ENTRY SKIPPED - invalid SL: stop_loss_level={stop_loss_level:.2f} <= current_price={current_price:.2f}"
            )
            return

        self.stop_loss_price = stop_loss_level
        stop_distance = stop_loss_level - current_price
        self.take_profit_price = current_price - self.params.risk_reward_ratio * stop_distance
        self.position_type = 'short'

        self.log_info(
            f">>> SHORT ENTRY [{dt_str}] | "
            f"Price={current_price:.2f} | "
            f"SL={self.stop_loss_price:.2f} (dist={stop_distance:.2f}) | "
            f"TP={self.take_profit_price:.2f} (dist={current_price - self.take_profit_price:.2f}) | "
            f"RR={self.params.risk_reward_ratio}"
        )

        self.order = self.sell()
        self.traded_in_short_trend = True  # Mark as traded in this red Trend A phase
        self._debug("Set traded_in_short_trend=True")

    def _check_exit(self):
        """Check and execute exit conditions."""
        current_price = self.data.close[0]
        current_low = self.data.low[0]
        current_high = self.data.high[0]
        dt_str = self._get_datetime_str()

        if self.position_type == 'long':
            # Log current position status
            self._debug(
                f"LONG POSITION CHECK | "
                f"H={current_high:.2f} L={current_low:.2f} C={current_price:.2f} | "
                f"SL={self.stop_loss_price:.2f} TP={self.take_profit_price:.2f} | "
                f"SL_hit={current_low <= self.stop_loss_price} TP_hit={current_high >= self.take_profit_price}"
            )

            # Long exit: stop loss hit or take profit hit
            if current_low <= self.stop_loss_price:
                self.log_info(
                    f"<<< LONG STOP LOSS [{dt_str}] | "
                    f"Low={current_low:.2f} <= SL={self.stop_loss_price:.2f} | "
                    f"Close={current_price:.2f}"
                )
                self.order = self.close()
                self._reset_position()
            elif current_high >= self.take_profit_price:
                self.log_info(
                    f"<<< LONG TAKE PROFIT [{dt_str}] | "
                    f"High={current_high:.2f} >= TP={self.take_profit_price:.2f} | "
                    f"Close={current_price:.2f}"
                )
                self.order = self.close()
                self._reset_position()

        elif self.position_type == 'short':
            # Log current position status
            self._debug(
                f"SHORT POSITION CHECK | "
                f"H={current_high:.2f} L={current_low:.2f} C={current_price:.2f} | "
                f"SL={self.stop_loss_price:.2f} TP={self.take_profit_price:.2f} | "
                f"SL_hit={current_high >= self.stop_loss_price} TP_hit={current_low <= self.take_profit_price}"
            )

            # Short exit: stop loss hit or take profit hit
            if current_high >= self.stop_loss_price:
                self.log_info(
                    f"<<< SHORT STOP LOSS [{dt_str}] | "
                    f"High={current_high:.2f} >= SL={self.stop_loss_price:.2f} | "
                    f"Close={current_price:.2f}"
                )
                self.order = self.close()
                self._reset_position()
            elif current_low <= self.take_profit_price:
                self.log_info(
                    f"<<< SHORT TAKE PROFIT [{dt_str}] | "
                    f"Low={current_low:.2f} <= TP={self.take_profit_price:.2f} | "
                    f"Close={current_price:.2f}"
                )
                self.order = self.close()
                self._reset_position()

    def _reset_position(self):
        """Reset position tracking variables."""
        self._debug(
            f"POSITION RESET | "
            f"entry_price={self.entry_price} -> None | "
            f"position_type={self.position_type} -> None"
        )
        self.entry_price = None
        self.stop_loss_price = None
        self.take_profit_price = None
        self.position_type = None

    def notify_order(self, order):
        """Handle order notifications."""
        dt_str = self._get_datetime_str()

        if order.status in [order.Submitted, order.Accepted]:
            status = "Submitted" if order.status == order.Submitted else "Accepted"
            self._debug(f"ORDER {status}: ref={order.ref}")
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.entry_price = order.executed.price
                self.log_info(
                    f"=== BUY EXECUTED [{dt_str}] | "
                    f"ref={order.ref} | "
                    f"price={order.executed.price:.2f} | "
                    f"size={order.executed.size:.4f} | "
                    f"value={order.executed.value:.2f} | "
                    f"comm={order.executed.comm:.2f}"
                )
            elif order.issell():
                if self.position_type == 'short' and self.entry_price is None:
                    self.entry_price = order.executed.price
                self.log_info(
                    f"=== SELL EXECUTED [{dt_str}] | "
                    f"ref={order.ref} | "
                    f"price={order.executed.price:.2f} | "
                    f"size={order.executed.size:.4f} | "
                    f"value={order.executed.value:.2f} | "
                    f"comm={order.executed.comm:.2f}"
                )

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            status_map = {order.Canceled: "Canceled", order.Margin: "Margin", order.Rejected: "Rejected"}
            status = status_map.get(order.status, "Unknown")
            self.log_info(f"!!! ORDER {status} [{dt_str}] | ref={order.ref}")
            self._reset_position()

        self.order = None

    def notify_trade(self, trade):
        """Handle trade notifications."""
        if not trade.isclosed:
            return

        dt_str = self._get_datetime_str()
        self.log_info(
            f"*** TRADE CLOSED [{dt_str}] | "
            f"ref={trade.ref} | "
            f"PnL={trade.pnl:.2f} | "
            f"Net PnL={trade.pnlcomm:.2f} | "
            f"size={trade.size:.4f}"
        )
