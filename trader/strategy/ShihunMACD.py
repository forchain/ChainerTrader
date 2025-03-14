from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt
from trader.strategy.trilogy_strategy import TrilogyStrategy

# Shihun MACD strategy
class ShihunMACDStrategy(TrilogyStrategy):
    params = (
        ('confirm', 3),
    )

    def __init__(self):
        super().__init__()

        self.dataclose = self.datas[0].close

        self.order = None
        self.goldenFork = 0
        self.deathFork = 0

        self.macd = bt.indicators.MACD(self.datas[0])

        self.mcross = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)

    def next(self):
        super().next()

        if self.order:
            return

        # histo2 = self.macd.macd[-2] - self.macd.signal[-2]
        # histo1 = self.macd.macd[-1] - self.macd.signal[-1]
        # histo0 = self.macd.macd[0] - self.macd.signal[0]
        if self.mcross[0] > 0:
           self.goldenFork = self.params.confirm
           self.deathFork = 0

        if self.mcross[0] < 0:
           self.goldenFork = 0
           self.deathFork = self.params.confirm

        if self.goldenFork > 0:
            if not self.position and self.macd.signal[-2] > 0 and self.macd.signal[-1] > 0 and self.macd.signal[0] > 0 and self.canBuy():
                self.log_info(f'Kline:{self.cur_datetime()}, 创建 买单:{self.dataclose[0]:.2f}')
                self.order = self.buy()
                self.goldenFork = 0
            else:
                self.goldenFork -= 1


        if self.deathFork > 0:
            if self.position and (self.macd.signal[-2] > self.macd.signal[-1] and self.macd.signal[-1] > self.macd.signal[0] or self.canSell()):
                self.log_info(f'Kline:{self.cur_datetime()}, 创建 卖单:{self.dataclose[0]:.2f}')
                self.order = self.sell()
                self.deathFork = 0
