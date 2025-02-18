from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt
from trader.strategy.trilogy_strategy import TrilogyStrategy


# Shihun RSI strategy
class ShihunRSIStrategy(TrilogyStrategy):
    params = (
        ('overbought', 70),
        ('oversold', 30),
    )

    def __init__(self):
        super().__init__()
        self.dataclose = self.datas[0].close

        self.order = None

        self.rsi = bt.indicators.RSI(self.datas[0], period=self.params.period)

    def next(self):
        super().next()

        if self.order:
            return

        if not self.position:
            if self.rsi[0] > self.params.overbought or self.canSell():
                self.buy()
        else:
            if self.rsi[0] < self.params.oversold:
                if self.canBuy():
                    self.sell()
                elif self.need_stop_loss():
                    self.sell()
