import backtrader as bt
import numpy as np
import statsmodels.api as sm

class RSRSIndicator(bt.Indicator):
    lines = ('beta', 'zscore')
    params = (
        ('period', 15),
        ('std_period', 500)
    )

    def __init__(self):
        self.addminperiod(self.params.period)

    def next(self):
        lows = np.array(self.data.low.get(size=self.params.period))
        highs = np.array(self.data.high.get(size=self.params.period))

        if len(lows) < self.params.period:
            return

        temp = sm.add_constant(lows)
        model = sm.OLS(highs, temp).fit()
        beta = model.params[1]  # get β

        self.lines.beta[0] = beta

        if len(self) > self.p.std_period:
            beta_series = np.array(self.lines.beta.get(size=self.params.std_period))
            beta_mean = np.mean(beta_series)
            beta_std = np.std(beta_series)
            self.lines.zscore[0] = (beta - beta_mean) / beta_std if beta_std != 0 else 0
        else:
            self.lines.zscore[0] = 0