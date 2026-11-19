import backtrader as bt

from trader.core.strategy.domain.indicators import rsrs_beta, rsrs_zscore


class RSRSIndicator(bt.Indicator):
    lines = ("beta", "zscore")
    params = (("period", 15), ("std_period", 500))

    def __init__(self):
        self.addminperiod(self.params.period)

    def next(self):
        lows = self.data.low.get(size=self.params.period)
        highs = self.data.high.get(size=self.params.period)

        if len(lows) < self.params.period:
            return

        beta = rsrs_beta(lows, highs)

        self.lines.beta[0] = beta

        if len(self) > self.p.std_period:
            self.lines.zscore[0] = rsrs_zscore(beta, self.lines.beta.get(size=self.params.std_period))
        else:
            self.lines.zscore[0] = 0
