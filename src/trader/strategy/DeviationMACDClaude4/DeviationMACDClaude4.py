from __future__ import absolute_import, division, print_function, unicode_literals

from collections import deque

import backtrader as bt

from trader.strategy.base_strategy import BaseStrategy


class DeviationMACDClaude4Strategy(BaseStrategy):
    """
    DeviationMACD Strategy - Python implementation of Pine Script
    Based on MACD divergence detection with ATR-based stop loss
    """

    params = (
        # Base parameters
        ("period", 12),
        ("name", "DeviationMACDClaude4"),
        # MACD parameters
        ("macd_fast", 12),
        ("macd_slow", 26),
        ("macd_signal", 9),
        # Stop loss and take profit
        ("take_profit_perc", 15.0),
        ("stop_loss_perc", 15.0),
        # ATR parameters
        ("atr_period", 12),
        ("atr_smoothing", "RMA"),  # RMA, SMA, EMA, WMA
        # Divergence parameters
        ("source_type", "Close"),  # 'Close' or 'High/Low'
        ("search_div", "Regular"),  # 'Regular', 'Hidden', 'Regular/Hidden'
        ("show_limit", 1),  # Minimum number of divergences
        ("max_pivot_points", 10),  # Maximum pivot points to check
        ("max_bars", 100),  # Maximum bars to check
        ("dont_confirm", False),  # Don't wait for confirmation
        # Pivot detection period
        ("pivot_period", 12),
    )

    def __init__(self):
        super().__init__()

        # Initialize MACD indicator
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.params.macd_fast,
            period_me2=self.params.macd_slow,
            period_signal=self.params.macd_signal,
        )

        # Delta MACD (histogram)
        self.delta_macd = self.macd.macd - self.macd.signal

        # Initialize ATR with proper smoothing
        if self.params.atr_smoothing == "RMA":
            self.atr_indicator = bt.indicators.ATR(
                self.data,
                period=self.params.atr_period,
                movav=bt.indicators.SmoothedMovingAverage,
            )
        elif self.params.atr_smoothing == "SMA":
            self.atr_indicator = bt.indicators.ATR(
                self.data,
                period=self.params.atr_period,
                movav=bt.indicators.SimpleMovingAverage,
            )
        elif self.params.atr_smoothing == "EMA":
            self.atr_indicator = bt.indicators.ATR(
                self.data,
                period=self.params.atr_period,
                movav=bt.indicators.ExponentialMovingAverage,
            )
        else:  # WMA
            self.atr_indicator = bt.indicators.ATR(
                self.data,
                period=self.params.atr_period,
                movav=bt.indicators.WeightedMovingAverage,
            )

        # Initialize pivot point storage
        self.ph_positions = deque(maxlen=self.params.max_pivot_points)
        self.pl_positions = deque(maxlen=self.params.max_pivot_points)
        self.ph_vals = deque(maxlen=self.params.max_pivot_points)
        self.pl_vals = deque(maxlen=self.params.max_pivot_points)

        # Trade management
        self.profit_price = 0.0
        self.loss_price = 0.0

        # Internal state
        self.bar_index = 0

    def get_price_source(self, bar_offset=0):
        """Get price based on source type configuration"""
        if self.params.source_type == "Close":
            return self.data.close[bar_offset]
        else:
            # For High/Low mode, return appropriate price based on context
            return self.data.close[bar_offset]

    def is_pivot_high(self, bars_back):
        """Check if a bar is a pivot high"""
        if len(self.data) <= bars_back + self.params.pivot_period:
            return False

        period = self.params.pivot_period
        center_idx = -bars_back

        if self.params.source_type == "High/Low":
            center_price = self.data.high[center_idx]
            # Check left side
            for i in range(1, period + 1):
                if self.data.high[center_idx - i] >= center_price:
                    return False
            # Check right side
            for i in range(1, period + 1):
                if self.data.high[center_idx + i] >= center_price:
                    return False
        else:  # Close
            center_price = self.data.close[center_idx]
            # Check left side
            for i in range(1, period + 1):
                if self.data.close[center_idx - i] >= center_price:
                    return False
            # Check right side
            for i in range(1, period + 1):
                if self.data.close[center_idx + i] >= center_price:
                    return False

        return True

    def is_pivot_low(self, bars_back):
        """Check if a bar is a pivot low"""
        if len(self.data) <= bars_back + self.params.pivot_period:
            return False

        period = self.params.pivot_period
        center_idx = -bars_back

        if self.params.source_type == "High/Low":
            center_price = self.data.low[center_idx]
            # Check left side
            for i in range(1, period + 1):
                if self.data.low[center_idx - i] <= center_price:
                    return False
            # Check right side
            for i in range(1, period + 1):
                if self.data.low[center_idx + i] <= center_price:
                    return False
        else:  # Close
            center_price = self.data.close[center_idx]
            # Check left side
            for i in range(1, period + 1):
                if self.data.close[center_idx - i] <= center_price:
                    return False
            # Check right side
            for i in range(1, period + 1):
                if self.data.close[center_idx + i] <= center_price:
                    return False

        return True

    def positive_divergence(self, indicator_data, divergence_type):
        """
        Check for positive divergence (regular or hidden)
        divergence_type: 1 = regular, 2 = hidden
        """
        if len(self.pl_positions) == 0:
            return 0

        startpoint = 0 if self.params.dont_confirm else 1

        # Check condition for divergence detection
        current_indicator = indicator_data[0]
        prev_indicator = indicator_data[1] if len(indicator_data) > 1 else current_indicator
        current_price = self.data.close[0]
        # Use a safer way to access previous price
        try:
            prev_price = self.data.close[1] if len(self.data) > 1 else current_price
        except IndexError:
            prev_price = current_price

        if not self.params.dont_confirm:
            if current_indicator <= prev_indicator and current_price <= prev_price:
                return 0

        # Check against pivot lows
        for i, pl_pos in enumerate(self.pl_positions):
            bars_diff = self.bar_index - pl_pos

            if bars_diff > self.params.max_bars:
                break

            if bars_diff > 5:
                pl_val = self.pl_vals[i]
                indicator_at_pivot = indicator_data[bars_diff] if bars_diff < len(indicator_data) else 0

                if self.params.source_type == "High/Low":
                    try:
                        price_comparison = self.data.low[startpoint]
                    except IndexError:
                        price_comparison = self.data.low[0]
                else:
                    try:
                        price_comparison = self.data.close[startpoint]
                    except IndexError:
                        price_comparison = self.data.close[0]

                # Regular positive divergence: price lower, indicator higher
                if divergence_type == 1:
                    if current_indicator > indicator_at_pivot and price_comparison < pl_val:
                        return bars_diff

                # Hidden positive divergence: price higher, indicator lower
                elif divergence_type == 2:
                    if current_indicator < indicator_at_pivot and price_comparison > pl_val:
                        return bars_diff

        return 0

    def negative_divergence(self, indicator_data, divergence_type):
        """
        Check for negative divergence (regular or hidden)
        divergence_type: 1 = regular, 2 = hidden
        """
        if len(self.ph_positions) == 0:
            return 0

        startpoint = 0 if self.params.dont_confirm else 1

        # Check condition for divergence detection
        current_indicator = indicator_data[0]
        prev_indicator = indicator_data[1] if len(indicator_data) > 1 else current_indicator
        current_price = self.data.close[0]
        # Use a safer way to access previous price
        try:
            prev_price = self.data.close[1] if len(self.data) > 1 else current_price
        except IndexError:
            prev_price = current_price

        if not self.params.dont_confirm:
            if current_indicator >= prev_indicator and current_price >= prev_price:
                return 0

        # Check against pivot highs
        for i, ph_pos in enumerate(self.ph_positions):
            bars_diff = self.bar_index - ph_pos

            if bars_diff > self.params.max_bars:
                break

            if bars_diff > 5:
                ph_val = self.ph_vals[i]
                indicator_at_pivot = indicator_data[bars_diff] if bars_diff < len(indicator_data) else 0

                if self.params.source_type == "High/Low":
                    try:
                        price_comparison = self.data.high[startpoint]
                    except IndexError:
                        price_comparison = self.data.high[0]
                else:
                    try:
                        price_comparison = self.data.close[startpoint]
                    except IndexError:
                        price_comparison = self.data.close[0]

                # Regular negative divergence: price higher, indicator lower
                if divergence_type == 1:
                    if current_indicator < indicator_at_pivot and price_comparison > ph_val:
                        return bars_diff

                # Hidden negative divergence: price lower, indicator higher
                elif divergence_type == 2:
                    if current_indicator > indicator_at_pivot and price_comparison < ph_val:
                        return bars_diff

        return 0

    def calculate_divergences(self):
        """Calculate all types of divergences"""
        # Get MACD histogram data as list for easier access
        delta_macd_list = []
        for i in range(min(len(self.delta_macd.array), self.params.max_bars + 10)):
            try:
                delta_macd_list.append(self.delta_macd[-i])
            except IndexError:
                break

        divergences = [0, 0, 0, 0]  # pos_reg, neg_reg, pos_hid, neg_hid

        if self.params.search_div in ["Regular", "Regular/Hidden"]:
            divergences[0] = self.positive_divergence(delta_macd_list, 1)  # Regular positive
            divergences[1] = self.negative_divergence(delta_macd_list, 1)  # Regular negative

        if self.params.search_div in ["Hidden", "Regular/Hidden"]:
            divergences[2] = self.positive_divergence(delta_macd_list, 2)  # Hidden positive
            divergences[3] = self.negative_divergence(delta_macd_list, 2)  # Hidden negative

        # Check minimum divergence limit
        total_divs = sum(1 for d in divergences if d > 0)
        if total_divs < self.params.show_limit:
            divergences = [0, 0, 0, 0]

        return divergences

    def next(self):
        super().next()

        # Update bar index
        self.bar_index = len(self.data) - 1

        # Need enough bars for pivot detection
        if len(self.data) < self.params.pivot_period * 2 + 1:
            return

        # Check for new pivot points (look back by pivot_period)
        bars_back = self.params.pivot_period

        # Check for pivot high
        if self.is_pivot_high(bars_back):
            pivot_bar_index = self.bar_index - bars_back
            if self.params.source_type == "High/Low":
                pivot_value = self.data.high[-bars_back]
            else:
                pivot_value = self.data.close[-bars_back]

            self.ph_positions.appendleft(pivot_bar_index)
            self.ph_vals.appendleft(pivot_value)

        # Check for pivot low
        if self.is_pivot_low(bars_back):
            pivot_bar_index = self.bar_index - bars_back
            if self.params.source_type == "High/Low":
                pivot_value = self.data.low[-bars_back]
            else:
                pivot_value = self.data.close[-bars_back]

            self.pl_positions.appendleft(pivot_bar_index)
            self.pl_vals.appendleft(pivot_value)

        # Calculate divergences
        divergences = self.calculate_divergences()
        pos_reg_div, neg_reg_div, pos_hid_div, neg_hid_div = divergences

        # Determine if divergences are detected
        pos_div_detected = pos_reg_div > 0 or pos_hid_div > 0
        neg_div_detected = neg_reg_div > 0 or neg_hid_div > 0

        if not self.can_trade():
            return

        # Trading logic
        opt_buy = False
        opt_sell = False

        # Buy signal: positive divergence and no position
        if pos_div_detected and self.position.size == 0:
            opt_buy = True

        # Sell signal: negative divergence and long position
        if neg_div_detected and self.position.size > 0:
            opt_sell = True

        # Stop loss check
        if self.position.size > 0 and self.loss_price > 0:
            if self.data.close[0] < self.loss_price:
                self.log_info(f"STOP LOSS triggered at {self.data.close[0]:.2f}, loss price: {self.loss_price:.2f}")
                self.close()
                self.profit_price = 0.0
                self.loss_price = 0.0
                return

        # Execute trades
        if opt_buy and not self.order:
            self.log_info(f"BUY signal detected - Divergence buy at {self.data.close[0]:.2f}")
            self.order = self.buy()

            # Calculate ATR-based stop loss and take profit
            current_atr = self.atr_indicator[0]
            self.profit_price = self.data.high[0] + current_atr * (self.params.take_profit_perc / 100.0)
            self.loss_price = self.data.low[0] - current_atr * (self.params.stop_loss_perc / 100.0)

            self.log_info(f"Set profit target: {self.profit_price:.2f}, stop loss: {self.loss_price:.2f}")

        elif opt_sell and not self.order:
            self.log_info(f"SELL signal detected - Divergence sell at {self.data.close[0]:.2f}")
            self.order = self.close()
            self.profit_price = 0.0
            self.loss_price = 0.0

    def notify_order(self, order):
        """Override to handle order completion"""
        super().notify_order(order)

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log_info(f"买入成功 - 价格: {order.executed.price:.2f}")
            else:
                self.log_info(f"卖出成功 - 价格: {order.executed.price:.2f}")
