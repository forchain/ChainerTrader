from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from trader.strategy.base_strategy import BaseStrategy
from trader.utils.operate import OperateType
import backtrader as bt

class AberrationStrategy(BaseStrategy):
    params = (
        ('devfactor', 2.0),
    )

    def __init__(self):
        super().__init__()
        self.params.period = 20
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
        midBand = self.bollinger.lines.mid[0]
        lowerBand = self.bollinger.lines.bot[0]

        if not self.position:
            if self.data.close[0] > upperBand:
                self.buy()
                self.update_stop_loss_point()
        else:
            if self.need_stop_loss():
                self.sell()
            else:
                if self.data.close[0] < lowerBand:
                    self.sell()