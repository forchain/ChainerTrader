from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os.path
import sys

from backtrader import num2date

from trader.binance.csvdata import BinanceCSVData
from trader.node import Node
from trader.utils import path

import backtrader as bt

from trader.utils.chainerstrategy import ChainerStrategy


# Shihun RSI strategy
class ShihunRSIStrategy(bt.Strategy):
    params = (
        ('atr', False),
        ('period', 14),
        ('overbought', 70),
        ('oversold', 30),
    )

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime[0]
        dat = num2date(dt)
        print(f"{dat}, {txt}")

    def __init__(self):
        super().__init__()

        self.dataclose = self.datas[0].close

        self.order = None

        self.rsi = bt.indicators.RSI(self.datas[0], period=self.params.period)

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
            if self.rsi[0] > self.params.overbought:
                self.sell()
        else:
            if self.rsi[0] < self.params.oversold:
                self.buy()



def shihunRSI(main=False,commission=0.001,atr=True):
    node = Node(ShihunRSIStrategy, main, commission, atr)
    node.start()

if __name__ == '__main__':
    shihunRSI(True)