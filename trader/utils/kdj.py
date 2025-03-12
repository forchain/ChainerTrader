import backtrader as bt

class KDJIndicator(bt.Indicator):
    lines = ("K", "D", "J")
    params = (("period", 9), ("smooth", 3))

    def __init__(self):
        low_min = bt.indicators.Lowest(self.data.low, period=self.params.period)
        high_max = bt.indicators.Highest(self.data.high, period=self.params.period)
        rsv = 100 * (self.data.close - low_min) / (high_max - low_min)

        self.lines.K = bt.indicators.EMA(rsv, period=self.params.smooth)
        self.lines.D = bt.indicators.EMA(self.lines.K, period=self.params.smooth)
        self.lines.J = 3 * self.lines.K - 2 * self.lines.D