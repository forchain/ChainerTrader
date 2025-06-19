from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

"""
DeviationMACD (o3 edition)
--------------------------
Python implementation of the DeviationMACD Pine-Script strategy that ships
with this repository (see `DeviationMACD.pine`).  The algorithm identifies
MACD divergences (regular & hidden) using pivot-point detection and manages
positions with ATR based profit-target / stop-loss bands.

The class follows ChainerTrader's `BaseStrategy` interface so it can be
loaded exactly like every other built-in strategy:

>>> cerebro.addstrategy(DeviationMACDO3)

No existing source files are modified – this module is completely
self-contained under the *DeviationMACD* package.
"""

import backtrader as bt
from collections import deque

from trader.strategy.base_strategy import BaseStrategy


class DeviationMACDO3(BaseStrategy):
    """DeviationMACD strategy – o3 implementation"""

    params = (
        # Basic
        ("name", "DeviationMACDO3"),

        # MACD configuration (identical to Pine defaults)
        ("macd_fast", 12),   # period
        ("macd_slow", 26),
        ("macd_signal", 9),

        # Divergence / pivot-point configuration
        ("pivot_period", 12),        # same meaning as Pine `period`
        ("max_pivot_points", 10),
        ("max_bars", 100),
        ("search_div", "Regular/Hidden"),  # options: Regular / Hidden / Regular/Hidden
        ("show_limit", 1),             # minimum #divergences required
        ("dont_confirm", False),
        ("source_type", "Close"),      # Close or High/Low

        # Risk management
        ("take_profit_perc", 15.0),    # expressed in percent of ATR
        ("stop_loss_perc", 15.0),
        ("atr_period", 12),
        ("atr_smoothing", "RMA"),      # RMA, SMA, EMA, WMA
    )

    # ---------------------------------------------------------------------
    # INITIALISATION
    # ---------------------------------------------------------------------
    def __init__(self):
        super().__init__()

        # --- Indicators ---------------------------------------------------
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.params.macd_fast,
            period_me2=self.params.macd_slow,
            period_signal=self.params.macd_signal,
        )
        self.delta_macd = self.macd.macd - self.macd.signal

        # Select appropriate MA class for ATR smoothing
        _ma_cls = {
            "RMA": bt.indicators.SmoothedMovingAverage,
            "SMA": bt.indicators.SimpleMovingAverage,
            "EMA": bt.indicators.ExponentialMovingAverage,
            "WMA": bt.indicators.WeightedMovingAverage,
        }.get(self.params.atr_smoothing.upper(), bt.indicators.SmoothedMovingAverage)

        self.atr_ind = bt.indicators.ATR(self.data, period=self.params.atr_period, movav=_ma_cls)

        # --- Containers to hold recent pivot information ------------------
        self.ph_positions = deque(maxlen=self.params.max_pivot_points)  # indexes of pivot-high bars
        self.pl_positions = deque(maxlen=self.params.max_pivot_points)  # indexes of pivot-low bars
        self.ph_values = deque(maxlen=self.params.max_pivot_points)     # prices at pivot-high
        self.pl_values = deque(maxlen=self.params.max_pivot_points)     # prices at pivot-low

        # Trade management helpers
        self.profit_price = 0.0
        self.loss_price = 0.0
        self.order = None  # active order

    # ---------------------------------------------------------------------
    # PIVOT-POINT DETECTION HELPERS
    # ---------------------------------------------------------------------
    def _is_pivot_high(self, bars_back: int) -> bool:
        """Return *True* if bar *-bars_back* forms a pivot high."""
        p = self.params.pivot_period
        if len(self.data) < bars_back + p + 1:
            return False

        idx = -bars_back  # negative index into backtrader Lines

        center = self.data.high[idx] if self.params.source_type == "High/Low" else self.data.close[idx]

        # left side
        for i in range(1, p + 1):
            if (self.data.high if self.params.source_type == "High/Low" else self.data.close)[idx - i] >= center:
                return False
        # right side
        for i in range(1, p + 1):
            if (self.data.high if self.params.source_type == "High/Low" else self.data.close)[idx + i] >= center:
                return False
        return True

    def _is_pivot_low(self, bars_back: int) -> bool:
        """Return *True* if bar *-bars_back* forms a pivot low."""
        p = self.params.pivot_period
        if len(self.data) < bars_back + p + 1:
            return False

        idx = -bars_back
        center = self.data.low[idx] if self.params.source_type == "High/Low" else self.data.close[idx]

        for i in range(1, p + 1):
            if (self.data.low if self.params.source_type == "High/Low" else self.data.close)[idx - i] <= center:
                return False
        for i in range(1, p + 1):
            if (self.data.low if self.params.source_type == "High/Low" else self.data.close)[idx + i] <= center:
                return False
        return True

    # ---------------------------------------------------------------------
    # DIVERGENCE DETECTION LOGIC
    # ---------------------------------------------------------------------
    def _positive_divergence(self, hist, div_type: int) -> int:
        """
        Detect positive (bullish) divergences.
        Returns the distance *len* (in bars) between now and the pivot that
        created the divergence, or *0* if none detected.
        *div_type* == 1 ➜ regular; 2 ➜ hidden.
        """
        if not self.pl_positions:
            return 0

        sp = 0 if self.params.dont_confirm else 1
        cur_ind = hist[0]
        prev_ind = hist[1] if len(hist) > 1 else cur_ind
        cur_price = self.data.close[0]
        prev_price = self.data.close[-1] if len(self.data) > 1 else cur_price

        if not self.params.dont_confirm and (cur_ind <= prev_ind and cur_price <= prev_price):
            return 0

        for idx, pl_bar in enumerate(self.pl_positions):
            diff = (len(self.data) - 1) - pl_bar
            if diff > self.params.max_bars:
                break
            if diff <= 5:
                continue

            pivot_price = self.pl_values[idx]
            ind_at_pivot = hist[diff] if diff < len(hist) else 0
            price_cmp = (self.data.low[sp] if self.params.source_type == "High/Low" else self.data.close[sp])

            if div_type == 1:  # regular bullish
                if cur_ind > ind_at_pivot and price_cmp < pivot_price:
                    return diff
            else:  # hidden bullish
                if cur_ind < ind_at_pivot and price_cmp > pivot_price:
                    return diff
        return 0

    def _negative_divergence(self, hist, div_type: int) -> int:
        """Symmetric to *_positive_divergence* but for bearish cases."""
        if not self.ph_positions:
            return 0

        sp = 0 if self.params.dont_confirm else 1
        cur_ind = hist[0]
        prev_ind = hist[1] if len(hist) > 1 else cur_ind
        cur_price = self.data.close[0]
        prev_price = self.data.close[-1] if len(self.data) > 1 else cur_price

        if not self.params.dont_confirm and (cur_ind >= prev_ind and cur_price >= prev_price):
            return 0

        for idx, ph_bar in enumerate(self.ph_positions):
            diff = (len(self.data) - 1) - ph_bar
            if diff > self.params.max_bars:
                break
            if diff <= 5:
                continue

            pivot_price = self.ph_values[idx]
            ind_at_pivot = hist[diff] if diff < len(hist) else 0
            price_cmp = (self.data.high[sp] if self.params.source_type == "High/Low" else self.data.close[sp])

            if div_type == 1:  # regular bearish
                if cur_ind < ind_at_pivot and price_cmp > pivot_price:
                    return diff
            else:  # hidden bearish
                if cur_ind > ind_at_pivot and price_cmp < pivot_price:
                    return diff
        return 0

    def _calc_divergences(self):
        """Return tuple (pos_reg, neg_reg, pos_hid, neg_hid)."""
        # Build a list of MACD histogram values (index 0 = current bar)
        hist = [self.delta_macd[-i] for i in range(min(len(self.delta_macd), self.params.max_bars + 10))]

        pos_reg = neg_reg = pos_hid = neg_hid = 0
        if self.params.search_div in ("Regular", "Regular/Hidden"):
            pos_reg = self._positive_divergence(hist, 1)
            neg_reg = self._negative_divergence(hist, 1)
        if self.params.search_div in ("Hidden", "Regular/Hidden"):
            pos_hid = self._positive_divergence(hist, 2)
            neg_hid = self._negative_divergence(hist, 2)

        # Enforce minimum divergence threshold
        if sum(1 for d in (pos_reg, neg_reg, pos_hid, neg_hid) if d > 0) < self.params.show_limit:
            return 0, 0, 0, 0
        return pos_reg, neg_reg, pos_hid, neg_hid

    # ---------------------------------------------------------------------
    # MAIN LOOP
    # ---------------------------------------------------------------------
    def next(self):
        super().next()

        # Update pivot lists – evaluate the bar *pivot_period* bars ago so
        # the pivot can be confirmed on both sides.
        pb = self.params.pivot_period
        if len(self.data) > pb * 2:
            if self._is_pivot_high(pb):
                bar_idx = len(self.data) - 1 - pb
                price = self.data.high[-pb] if self.params.source_type == "High/Low" else self.data.close[-pb]
                self.ph_positions.appendleft(bar_idx)
                self.ph_values.appendleft(price)
            if self._is_pivot_low(pb):
                bar_idx = len(self.data) - 1 - pb
                price = self.data.low[-pb] if self.params.source_type == "High/Low" else self.data.close[-pb]
                self.pl_positions.appendleft(bar_idx)
                self.pl_values.appendleft(price)

        # Evaluate divergences
        divs = self._calc_divergences()
        pos_div = divs[0] > 0 or divs[2] > 0
        neg_div = divs[1] > 0 or divs[3] > 0

        # Stop-loss handling (close position if triggered)
        if self.position and self.loss_price:
            if self.data.close[0] < self.loss_price:
                self.log_info(f"Stop-loss hit @ {self.data.close[0]:.2f} (threshold {self.loss_price:.2f})")
                self.close()
                self.profit_price = self.loss_price = 0.0
                return

        # Place orders -----------------------------------------------------
        if not self.position and pos_div and not self.order:
            self.log_info(f"BUY due to positive divergence @ {self.data.close[0]:.2f}")
            self.order = self.buy()

            atr_now = self.atr_ind[0]
            self.profit_price = self.data.high[0] + atr_now * (self.params.take_profit_perc / 100.0)
            self.loss_price = self.data.low[0] - atr_now * (self.params.stop_loss_perc / 100.0)
            self.log_info(f"Set TP {self.profit_price:.2f} / SL {self.loss_price:.2f}")

        elif self.position and neg_div and not self.order:
            self.log_info(f"SELL due to negative divergence @ {self.data.close[0]:.2f}")
            self.order = self.close()
            self.profit_price = self.loss_price = 0.0

    # ---------------------------------------------------------------------
    # ORDER CALLBACK
    # ---------------------------------------------------------------------
    def notify_order(self, order):
        super().notify_order(order)
        # Reset local order tracker so new signals can be executed
        if order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected):
            self.order = None 