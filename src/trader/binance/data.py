from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from datetime import datetime

import backtrader as bt
from backtrader import date2num

from trader.utils.kline import Kline


class BinanceData(bt.feed.DataBase):
    def __init__(self, data:[Kline]):
        super().__init__()
        self.data = data
        self.index = 0

    def _load(self):
        if self.index >= len(self.data):
            return False
        kl = self.data[self.index]
        self.lines.datetime[0] = date2num(datetime.fromtimestamp(kl.open_time))
        self.lines.open[0] = kl.open
        self.lines.high[0] = kl.high
        self.lines.low[0] = kl.low
        self.lines.close[0] = kl.close
        self.lines.volume[0] = kl.volume
        self.index += 1
        return True