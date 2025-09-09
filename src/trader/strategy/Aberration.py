from __future__ import absolute_import, division, print_function, unicode_literals

import backtrader as bt

from trader.strategy.base_strategy import BaseStrategy


class AberrationStrategy(BaseStrategy):
    params = (("devfactor", 2.0),)

    def __init__(self):
        super().__init__()
        self.params.period = 20
        self.order = None

        self.ma = bt.indicators.SMA(self.data.close, period=self.params.period)
        self.std = bt.indicators.StdDev(self.data.close, period=self.params.period)
        self.upper = self.ma + self.params.devfactor * self.std
        self.lower = self.ma - self.params.devfactor * self.std

    def next(self):
        super().next()
        if self.order:
            return

        if not self.can_trade():
            return

        if not self.position:
            if self.data.close[0] > self.upper[0]:
                self.buy()
                self.update_stop_loss_point()
        else:
            if self.need_stop_loss():
                self.sell()
            else:
                if self.data.close[0] < self.ma[0]:
                    self.sell()
