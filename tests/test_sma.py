from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os.path

from backtrader import num2date

from trader.binance.csvdata import BinanceCSVData
from trader.common import path

import backtrader as bt
import backtrader.indicators as btind

from trader.strategy.trilogy_strategy import TrilogyStrategy

class SMAStrategy(TrilogyStrategy):
    params = (
        ('confirm', 3),
        ('period', 14),
    )

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime[0]
        dat = num2date(dt)
        print(f"{dat}, {txt}")

    def __init__(self):
        super().__init__()

        self.dataclose = self.datas[0].close

        self.order = None

        self.sma = btind.SimpleMovingAverage(self.datas[0], period=self.params.period)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(
                    '买入, 价格: %.2f, 花费: %.2f, 手续费: %.2f' %
                    (order.executed.price,
                     order.executed.value,
                     order.executed.comm))

                self.buyprice = order.executed.price
                self.buycomm = order.executed.comm
            else:  # Sell
                self.log('卖出, 价格: %.2f, 花费: %.2f, 手续费: %.2f' %
                         (order.executed.price,
                          order.executed.value,
                          order.executed.comm))

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('Order Canceled/Margin/Rejected')

        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return

        self.log('营业利润, 毛利润: %.2f, 净利润: %.2f' %
                 (trade.pnl, trade.pnlcomm))

    def next(self):
        self.log('收盘价, %.2f' % self.dataclose[0])

        if self.order:
            return

        if not self.position:
            if self.sma[0] < self.dataclose[0] or self.canSell():
                self.sell()
        else:
            if self.sma[0] > self.dataclose[0]:
                if self.canBuy():
                    self.buy()



def test_sma():
    cerebro = bt.Cerebro()

    cerebro.addstrategy(SMAStrategy)

    datapath = os.path.join(path.GetDatasDir(), 'ETHUSDT-1h-202301-202401.csv')

    data = BinanceCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2023, 1, 1),
        todate=datetime.datetime(2024, 1, 1),
    )

    cerebro.adddata(data)

    cerebro.broker.setcash(100000.0)

    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    cerebro.broker.setcommission(commission=0.0)

    print('\n初始资产: %.2f' % cerebro.broker.getvalue())

    cerebro.run()

    print('最终资产: %.2f' % cerebro.broker.getvalue())