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

from trader.utils.basestrategy import BaseStrategy
from trader.utils.chainerrsi import ChainerRSI, ChainerRSIHisto
from trader.utils.chainerstrategy import ChainerStrategy
from trader.utils.operate import OperateType
from trader.utils.trend import TrendType


# Shihun RSI strategy
class ShihunRSIStrategy(BaseStrategy):
    params = (
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

        self.rsi = ChainerRSIHisto(self.datas[0])

        self.criticalBuyK = None
        self.criticalSellK = None

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
        if self.order:
            return
        # self.log('收盘价, %.2f' % self.dataclose[0])

        # find criticalK
        find = False
        if self.rsi.signal[0] > 50:
            if  self.rsi.histo[0] > 0 and self.rsi.histo[0] > self.rsi.histo[-1] and self.rsi.histo[-1] > self.rsi.histo[-2] and self.rsi.histo[-2] < 0:
                find=True
            if self.rsi.rsi[0] > self.params.overbought:
                find=True

            if self.rsi.signal[-1] < 50 and self.rsi.signal[-2] < self.rsi.signal[-1]:
                curIdx = 0
                adjacentUnderpants = False
                while self.rsi.signal[curIdx] > self.rsi.signal[curIdx - 1]:
                    curIdx -= 1
                while self.rsi.signal[curIdx] < self.rsi.signal[curIdx - 1]:
                    if self.rsi.signal[curIdx] > 50:
                        adjacentUnderpants = True
                        break
                    curIdx -= 1
                if adjacentUnderpants:
                    find = True
            if find:
                if self.datas[0].close[0] > self.datas[0].open[0]:
                    self.criticalBuyK = self.datas[0].high[0]
                else:
                    find=False


        willOpt = OperateType.UNKNOWN

        if not self.position:
            if self.criticalBuyK and self.rsi.signal[0] > 50 and not find:
                if self.datas[0].close[0] > self.datas[0].open[0] and self.datas[0].close[0] > self.criticalBuyK:
                    willOpt = OperateType.BUY

        else:
            if self.stopLossPoint:
                if self.dataclose[0] < self.stopLossPoint:
                   willOpt = OperateType.SELL
            if self.rsi.rsi[0] < self.params.oversold:
                willOpt = OperateType.SELL
            if self.rsi.histo[0] < self.rsi.histo[-1] and self.rsi.histo[-1] < self.rsi.histo[-2] and self.rsi.histo[-2] > 0 and self.rsi.histo[0] < 0:
                willOpt = OperateType.SELL


        if willOpt == OperateType.SELL:
            self.log('收盘价: %.2f (创建 卖单)' % self.dataclose[0])
            self.order = self.sell()
            self.criticalBuyK = None
            self.criticalSellK = None

        elif willOpt == OperateType.BUY:
            self.log('收盘价: %.2f (创建 买单)' % self.dataclose[0])
            self.order = self.buy()
            pdist=0
            if self.params.atr:
                pdist = self.atr[0] * self.params.atrdist
            self.stopLossPoint = self.datas[0].close[0] - pdist
            self.criticalBuyK = None
            self.criticalSellK = None




def shihunRSI(main=False,commission=0.001,atr=True):
    node = Node(ShihunRSIStrategy, main, commission, atr)
    node.start()

if __name__ == '__main__':
    shihunRSI(True)