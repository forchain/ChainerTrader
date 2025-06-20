from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import math
import os.path

from backtrader import num2date

from trader.common import path

import backtrader as bt

from trader.utils.pivot_high import PivotHigh
from trader.utils.pivot_low import PivotLow


class TestStrategy(bt.Strategy):

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        print('%s, %s' % (dt.isoformat(), txt))

    def __init__(self):
        self.ph = PivotHigh(self.data.high, left=3, right=3)
        self.pl = PivotLow(self.data.low, left=3, right=3)

    def next(self):
        if not math.isnan(self.ph.middle_value()):
            self.log(f"Pivot High on {num2date(self.datas[0].datetime[self.ph.middle_idx()])}:{self.ph.middle_value()}")

        if not math.isnan(self.pl.middle_value()):
            self.log(f"Pivot Low on {num2date(self.datas[0].datetime[self.ph.middle_idx()])}:{self.pl.middle_value()}")


def test_pivotind(main=False):
    print(main)
    cerebro = bt.Cerebro()

    cerebro.addstrategy(TestStrategy)

    datapath = os.path.join(path.GetDataDir(), 'orcl-1995-2014.txt')

    data = bt.feeds.YahooFinanceCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2000, 1, 1),
        todate=datetime.datetime(2000, 12, 31),
        reverse=False)

    cerebro.adddata(data)

    cerebro.broker.setcash(1000.0)

    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    cerebro.broker.setcommission(commission=0.0)


    cerebro.run()


    if main:
        cerebro.plot()

if __name__ == '__main__':
    test_pivotind(True)