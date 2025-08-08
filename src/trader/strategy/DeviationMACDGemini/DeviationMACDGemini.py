from __future__ import absolute_import, division, print_function, unicode_literals

import collections

import backtrader as bt

from trader.strategy.base_strategy import BaseStrategy


class PivotHigh(bt.Indicator):
    lines = ("ph",)
    params = (("period", 14), ("source", None))

    def __init__(self):
        self.addminperiod(self.p.period * 2 + 1)
        if self.p.source is None:
            self.p.source = self.data.high

    def next(self):
        is_pivot = True
        pivot_price = self.p.source[-self.p.period]
        for i in range(1, self.p.period + 1):
            if pivot_price < self.p.source[-self.p.period + i] or pivot_price < self.p.source[-self.p.period - i]:
                is_pivot = False
                break
        if is_pivot:
            self.lines.ph[0] = pivot_price
        else:
            self.lines.ph[0] = 0


class PivotLow(bt.Indicator):
    lines = ("pl",)
    params = (("period", 14), ("source", None))

    def __init__(self):
        self.addminperiod(self.p.period * 2 + 1)
        if self.p.source is None:
            self.p.source = self.data.low

    def next(self):
        is_pivot = True
        pivot_price = self.p.source[-self.p.period]
        for i in range(1, self.p.period + 1):
            if pivot_price > self.p.source[-self.p.period + i] or pivot_price > self.p.source[-self.p.period - i]:
                is_pivot = False
                break
        if is_pivot:
            self.lines.pl[0] = pivot_price
        else:
            self.lines.pl[0] = 0


class DeviationMACDGeminiStrategy(BaseStrategy):
    params = (
        # ('name','DeviationMACD_Gemini'),
        # base
        ("period", 12),
        # macd
        ("fast_length", 12),
        ("slow_length", 26),
        ("signal_length", 9),
        # stopLoss takeProfit
        ("stop_loss_perc", 15.0),
        # atr
        ("atr_smoothing", "RMA"),  # RMA, SMA, EMA, WMA
        # deviation
        ("div_source", "Close"),  # Close, High/Low
        ("div_type", "Regular"),  # Regular, Hidden, Regular/Hidden
        ("div_max_pp", 10),
        ("div_max_bars", 100),
        ("div_dont_confirm", False),
    )

    def __init__(self):
        super().__init__()
        self.set_default_period(self.p.period)

        self.macd = bt.indicators.MACD(
            self.data,
            period_me1=self.p.fast_length,
            period_me2=self.p.slow_length,
            period_signal=self.p.signal_length,
        )
        self.macd_hist = self.macd.histo

        atr_period = self.p.period
        tr = bt.indicators.TRANGE(self.data)
        if self.p.atr_smoothing == "RMA":
            self.atr_val = bt.indicators.RMA(tr, period=atr_period)
        elif self.p.atr_smoothing == "SMA":
            self.atr_val = bt.indicators.SMA(tr, period=atr_period)
        elif self.p.atr_smoothing == "EMA":
            self.atr_val = bt.indicators.EMA(tr, period=atr_period)
        else:
            self.atr_val = bt.indicators.WMA(tr, period=atr_period)

        price_source_high = self.data.high if self.p.div_source == "High/Low" else self.data.close
        price_source_low = self.data.low if self.p.div_source == "High/Low" else self.data.close
        self.pivot_high = PivotHigh(self.data, period=self.p.period, source=price_source_high)
        self.pivot_low = PivotLow(self.data, period=self.p.period, source=price_source_low)

        self.ph_positions = collections.deque(maxlen=self.p.div_max_pp)
        self.pl_positions = collections.deque(maxlen=self.p.div_max_pp)
        self.ph_vals = collections.deque(maxlen=self.p.div_max_pp)
        self.pl_vals = collections.deque(maxlen=self.p.div_max_pp)

        self.order = None
        self.loss_price = 0

    def next(self):
        super().next()

        if self.order:
            return

        # Pivot points tracking
        if self.pivot_high.ph[0] > 0:
            pivot_bar_index = len(self) - 1 - self.p.period
            self.ph_positions.appendleft(pivot_bar_index)
            self.ph_vals.appendleft(self.pivot_high.ph[0])

        if self.pivot_low.pl[0] > 0:
            pivot_bar_index = len(self) - 1 - self.p.period
            self.pl_positions.appendleft(pivot_bar_index)
            self.pl_vals.appendleft(self.pivot_low.pl[0])

        # Divergence detection
        pos_div = self.check_positive_divergence()
        neg_div = self.check_negative_divergence()

        # Trading logic
        if not self.position:
            if pos_div:
                self.log_info(f"BUY CREATE, {self.data.close[0]:.2f}")
                self.order = self.buy()
                self.loss_price = self.data.low[0] - (self.atr_val[0] * self.p.stop_loss_perc)
        else:
            if neg_div:
                self.log_info(f"SELL CREATE, {self.data.close[0]:.2f}")
                self.order = self.close()
                self.loss_price = 0
            # Stop loss check
            elif self.loss_price > 0 and self.data.close[0] < self.loss_price:
                self.log_info(f"STOP LOSS, {self.data.close[0]:.2f}")
                self.order = self.close()
                self.loss_price = 0

    def check_positive_divergence(self):
        if self.p.div_type in ["Regular", "Regular/Hidden"]:
            if self.positive_divergence_check(regular=True):
                return True
        if self.p.div_type in ["Hidden", "Regular/Hidden"]:
            if self.positive_divergence_check(regular=False):
                return True
        return False

    def check_negative_divergence(self):
        if self.p.div_type in ["Regular", "Regular/Hidden"]:
            if self.negative_divergence_check(regular=True):
                return True
        if self.p.div_type in ["Hidden", "Regular/Hidden"]:
            if self.negative_divergence_check(regular=False):
                return True
        return False

    def positive_divergence_check(self, regular=True):
        startpoint = 0 if self.p.div_dont_confirm else 1
        if not (self.p.div_dont_confirm or self.macd_hist[0] > self.macd_hist[-1] or self.data.close[0] > self.data.close[-1]):
            return False

        for i in range(len(self.pl_positions)):
            pivot_bar_index = self.pl_positions[i]
            len_to_pivot = (len(self) - 1 - startpoint) - pivot_bar_index

            if len_to_pivot > self.p.div_max_bars:
                break
            if len_to_pivot <= 5:
                continue

            price_now = (self.data.low if self.p.div_source == "High/Low" else self.data.close)[-startpoint]
            price_pivot = self.pl_vals[i]
            macd_now = self.macd_hist[-startpoint]
            macd_pivot = self.macd_hist[pivot_bar_index - (len(self) - 1)]

            regular_cond = regular and macd_now > macd_pivot and price_now < price_pivot
            hidden_cond = not regular and macd_now < macd_pivot and price_now > price_pivot

            if regular_cond or hidden_cond:
                return True
        return False

    def negative_divergence_check(self, regular=True):
        startpoint = 0 if self.p.div_dont_confirm else 1
        if not (self.p.div_dont_confirm or self.macd_hist[0] < self.macd_hist[-1] or self.data.close[0] < self.data.close[-1]):
            return False

        for i in range(len(self.ph_positions)):
            pivot_bar_index = self.ph_positions[i]
            len_to_pivot = (len(self) - 1 - startpoint) - pivot_bar_index

            if len_to_pivot > self.p.div_max_bars:
                break
            if len_to_pivot <= 5:
                continue

            price_now = (self.data.high if self.p.div_source == "High/Low" else self.data.close)[-startpoint]
            price_pivot = self.ph_vals[i]
            macd_now = self.macd_hist[-startpoint]
            macd_pivot = self.macd_hist[pivot_bar_index - (len(self) - 1)]

            regular_cond = regular and macd_now < macd_pivot and price_now > price_pivot
            hidden_cond = not regular and macd_now > macd_pivot and price_now < price_pivot

            if regular_cond or hidden_cond:
                return True
        return False
