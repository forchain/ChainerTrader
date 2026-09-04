from __future__ import absolute_import, division, print_function, unicode_literals

import backtrader as bt

from trader.strategy.base_strategy import BaseStrategy


class TURTLEStrategy(BaseStrategy):
    params = (
        ("period_R", 7),
        ("risk", 0.02),
    )

    def __init__(self):
        super().__init__()
        self.atr = bt.indicators.ATR(self.datas[0], period=14)
        self.highest = bt.indicators.Highest(self.data.high, period=self.params.period)

        self.lowest_R = bt.indicators.Lowest(self.data.low, period=self.params.period_R)

    def next(self):
        super().next()
        if self.order:
            return
        if not self.can_trade():
            return
        position_size = (self.broker.getvalue() * self.params.risk) / (self.atr[0] * 100)
        if not self.position:
            if self.data.close[0] > self.highest[-1]:
                self.log_info(f"Kline:{self.cur_datetime()}, 创建 买单:{self.data.close[0]:.2f}")
                self.order = self.buy(size=position_size)
        else:
            if self.data.close[0] < self.lowest_R[-1]:
                self.log_info(f"Kline:{self.cur_datetime()}, 创建 卖单:{self.data.close[0]:.2f}")
                self.close()
