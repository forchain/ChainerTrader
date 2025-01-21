from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt

from trader.strategy.base_strategy import BaseStrategy


# Bollinger Bands Mean Regression Strategy
class BollingerMeanRegStrategy(BaseStrategy):
    params = (
        ('devfactor', 2),       # 标准差系数
    )

    def __init__(self):
        super().__init__()
        self.params.period=20  # 布林带周期
        self.order = None

        self.bollinger = bt.indicators.BollingerBands(
            self.datas[0].close,
            period=self.params.period,
            devfactor=self.params.devfactor
        )

    def next(self):
        super().next()
        if self.order:
            return

        upperBand = self.bollinger.lines.top[0]
        lowerBand = self.bollinger.lines.bot[0]

        if not self.position:
            if self.data.low[0] < lowerBand and self.data.close[0] < self.data.open[0]:
                self.buy()
                self.update_stop_loss_point()
        else:
            if self.need_stop_loss():
                self.sell()
            else:
                if self.data.high[0] > upperBand and self.data.close[0] > self.data.open[0]:
                    self.sell()


