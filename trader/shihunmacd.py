from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os.path
import sys

from backtrader import num2date

from trader.binance.csvdata import BinanceCSVData
from trader.utils import path

import backtrader as bt

from trader.utils.chainerstrategy import ChainerStrategy


# Shihun MACD strategy
class ShihunMACDStrategy(ChainerStrategy):
    params = (
        ('confirm', 3),
    )

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime[0]
        dat = num2date(dt)
        print(f"{dat}, {txt}")

    def __init__(self):
        super().__init__()

        self.dataclose = self.datas[0].close

        self.order = None
        self.buyprice = None
        self.buycomm = None
        self.goldenFork = 0
        self.deathFork = 0

        self.macd = bt.indicators.MACD(self.datas[0])

        self.mcross = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)

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
                self.log('创建 买单, %.2f' % self.dataclose[0])
                self.order = self.buy()
                self.goldenFork = 0
            else:
                self.goldenFork -= 1


        if self.deathFork > 0:
            if self.position and (self.macd.signal[-2] > self.macd.signal[-1] and self.macd.signal[-1] > self.macd.signal[0] or self.canSell()):
                self.log('创建 卖单, %.2f' % self.dataclose[0])
                self.order = self.sell()
                self.deathFork = 0


def shihunMACD(main=False):
    cerebro = bt.Cerebro()

    cerebro.addstrategy(ShihunMACDStrategy)

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

    if main:
        cerebro.plot()

if __name__ == '__main__':
    shihunMACD(True)