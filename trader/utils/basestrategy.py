from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt
import array as arr

from trader.utils.inflectionpoint import InflectionType
from trader.utils.trend import TrendType


# chainer basic framework strategy
class BaseStrategy(bt.Strategy):
    params = (
        ('atr', False),
        ('atrperiod', 14),
        ('atrdist', 5),  # ATR distance for stop price
        ('mode', TrendType.NORMAL),
    )

    def __init__(self):
        super().__init__()
        # Stop loss point
        self.stopLossPoint=0
        # To set the stop price
        if self.params.atr:
            self.atr = bt.indicators.ATR(self.datas[0], period=self.params.atrperiod)
