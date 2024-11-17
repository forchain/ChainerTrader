from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os.path
from trader.common import path

import backtrader as bt

class TestStrategy(bt.Strategy):
    params = (
        ('maperiod', 15),
    )

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        print('%s, %s' % (dt.isoformat(), txt))

    def __init__(self):
        self.dataclose = self.datas[0].close

        self.order = None
        self.buyprice = None
        self.buycomm = None

        self.sma = bt.indicators.SimpleMovingAverage(self.datas[0], period=self.params.maperiod)

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

            self.bar_executed = len(self)

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

            if self.dataclose[0] > self.sma[0]:

                self.log('创建 买单, %.2f' % self.dataclose[0])

                self.order = self.buy()

        else:

            if self.dataclose[0] < self.sma[0]:
                self.log('创建 卖单, %.2f' % self.dataclose[0])

                self.order = self.sell()

def test_backtrader(main=False):
    print(main)
    cerebro = bt.Cerebro()

    cerebro.addstrategy(TestStrategy)

    datapath = os.path.join(path.GetDatasDir(), 'orcl-1995-2014.txt')

    data = bt.feeds.YahooFinanceCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2000, 1, 1),
        todate=datetime.datetime(2000, 12, 31),
        reverse=False)

    cerebro.adddata(data)

    cerebro.broker.setcash(1000.0)

    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    cerebro.broker.setcommission(commission=0.0)

    print('\n初始资产: %.2f' % cerebro.broker.getvalue())

    cerebro.run()

    print('最终资产: %.2f' % cerebro.broker.getvalue())

    if main:
        cerebro.plot()

if __name__ == '__main__':
    test_backtrader(True)