import math

import backtrader as bt


class SuperTrend(bt.Indicator):
    lines = ("up", "down", "trend", "buy_signal", "sell_signal")
    params = (
        ("period", 10),
        ("multiplier", 3.0),
        ("use_atr", True),  # True: use ATR, False: use SMA of TR
    )

    def __init__(self):
        self.plotinfo.plotmaster = self.data

        if self.p.use_atr:
            self.atr = bt.indicators.ATR(period=self.p.period)
        else:
            self.atr = bt.indicators.SMA(bt.indicators.TrueRange(), period=self.p.period)

    def next(self):
        self.lines.trend[0] = 1
        self.lines.up[0] = float("nan")
        self.lines.down[0] = float("nan")
        self.lines.buy_signal[0] = False
        self.lines.sell_signal[0] = False

        if math.isnan(self.lines.trend[-1]):
            return

        hl2 = (self.data.high[0] + self.data.low[0]) / 2

        self.lines.up[0] = hl2 - self.p.multiplier * self.atr[0]
        self.lines.down[0] = hl2 + self.p.multiplier * self.atr[0]

        up1 = self.lines.up[0]
        if not math.isnan(self.lines.up[-1]):
            up1 = self.lines.up[-1]

        if self.data.close[-1] > up1:
            if self.lines.up[0] < up1:
                self.lines.up[0] = up1

        dn1 = self.lines.down[0]
        if not math.isnan(self.lines.down[-1]):
            dn1 = self.lines.down[-1]

        if self.data.close[-1] < dn1:
            if self.lines.down[0] > dn1:
                self.lines.down[0] = dn1

        self.lines.trend[0] = self.lines.trend[-1]

        if self.lines.trend[0] == -1 and self.data.close[0] > dn1:
            self.lines.trend[0] = 1
        elif self.lines.trend[0] == 1 and self.data.close[0] < up1:
            self.lines.trend[0] = -1

        if self.lines.trend[0] == 1 and self.lines.trend[-1] == -1:
            self.lines.buy_signal[0] = True

        if self.lines.trend[0] == -1 and self.lines.trend[-1] == 1:
            self.lines.sell_signal[0] = True
