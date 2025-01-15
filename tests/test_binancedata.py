from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os

import backtrader
from backtrader import num2date

from trader.binance.csvdata import BinanceCSVData
from trader.common import path


class TestStrategy(backtrader.Strategy):

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime[0]
        dat = num2date(dt)
        print(f"{dat}, {txt}")

    def __init__(self):
        self.dataclose = self.datas[0].close

    def next(self):
        self.log('Close, %.2f' % self.dataclose[0])


def test_binanceData():
    cerebro = backtrader.Cerebro()
    cerebro.addstrategy(TestStrategy)

    datapath = os.path.join(path.GetDatasDir(), 'ETHUSDT-1h-202301-202401.csv')

    data = BinanceCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2023, 1, 1),
        todate=datetime.datetime(2024, 1, 1),
    )
    cerebro.adddata(data)
    cerebro.broker.setcash(100000.0)
    print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())
    cerebro.run()
    print('Final Portfolio Value: %.2f' % cerebro.broker.getvalue())