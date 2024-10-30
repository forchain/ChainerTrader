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


# Shihun MACD RSI BollingerBand strategy
class ShihunMacdRsiBollingerBandStrategy(BaseStrategy):
    params = (
        ('period', 20),         # 布林带周期
        ('devfactor', 2),       # 标准差系数
    )

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime[0]
        dat = num2date(dt)
        print(f"{dat}, {txt}")


    def __init__(self):
        super().__init__()

        self.dataclose = self.datas[0].close

        self.order = None

        self.macd = bt.indicators.MACDHisto(self.datas[0])
        self.bollinger = bt.indicators.BollingerBands(
            self.data.close,
            period=self.params.period,
            devfactor=self.params.devfactor
        )
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

        willOpt = OperateType.UNKNOWN
        curTrend = self.getTrend()
        if curTrend != TrendType.UP:
            if self.params.mode != TrendType.UP:
                willOpt = self.processShock()
        else:
            willOpt = self.processTrend()

        if willOpt == OperateType.SELL:
            self.log('收盘价: %.2f (创建 卖单)' % self.dataclose[0])
            self.order = self.sell()
            self.criticalBuyK = None
            self.criticalSellK = None

        elif willOpt == OperateType.BUY:
            self.log('收盘价: %.2f (创建 买单)' % self.dataclose[0])
            self.order = self.buy()
            pdist=self.datas[0].low[0]
            if self.datas[0].low[-1] < pdist:
                pdist=self.datas[0].low[-1]
            self.stopLossPoint = pdist
            self.criticalBuyK = None
            self.criticalSellK = None

    def getTrend(self):
        if self.macd.macd[0] > 0:
            return TrendType.UP
        return TrendType.DOWN

    def processShock(self):
        upperBand = self.bollinger.lines.top[0]
        lowerBand = self.bollinger.lines.bot[0]
        midBand = self.bollinger.lines.mid[0]

        # find criticalK
        find = False
        if self.data.close[0] < lowerBand and self.data.close[0] > self.data.open[0]:
            if self.macd.histo[0] < 0 and self.macd.histo[0] > self.macd.histo[-1] and self.macd.histo[-1] < self.macd.histo[-2]:
                find = True
            if self.rsi.histo[0] > 0 and self.rsi.histo[0] > self.rsi.histo[-1] and self.rsi.histo[-1] > self.rsi.histo[-2] and self.rsi.histo[-2] < 0:
                find = True
            if find:
                self.criticalBuyK = self.datas[0].high[0]

        willOpt = OperateType.UNKNOWN

        if not self.position:
            if self.criticalBuyK and self.macd.macd[0] > 0 and not find:
                if self.datas[0].close[0] > self.datas[0].open[0] and self.datas[0].close[0] > self.criticalBuyK:
                    willOpt = OperateType.BUY

        else:
            if self.stopLossPoint:
                if self.dataclose[0] < self.stopLossPoint:
                    willOpt = OperateType.SELL
            if willOpt == OperateType.UNKNOWN:
                if self.data.high[0] > upperBand:
                    willOpt = OperateType.SELL
                elif self.data.close[0] < midBand:
                    willOpt = OperateType.SELL

            if willOpt == OperateType.UNKNOWN:
                if self.macd.histo[0] < self.macd.histo[-1] and self.macd.histo[-1] > self.macd.histo[-2] and \
                        self.macd.histo[-2] > 0:
                    self.criticalSellK = self.datas[0].low[0]
                elif self.criticalSellK and self.datas[0].close[0] < self.datas[0].open[0] and self.datas[0].close[
                    0] < self.criticalSellK:
                    willOpt = OperateType.SELL

        return willOpt

    def processTrend(self):
        upperBand = self.bollinger.lines.top[0]
        lowerBand = self.bollinger.lines.bot[0]
        midBand = self.bollinger.lines.mid[0]

        # find criticalK
        find = False
        if self.data.close[0] > upperBand:
            if self.data.close[0] > self.data.open[0]:
                self.criticalBuyK = self.data.high[0]
                find = True

        if self.macd.macd[0] > 0 and self.macd.macd[-1] > 0 and self.macd.macd[-2] > 0:
            if self.macd.histo[0] < 0 and self.macd.histo[0] > self.macd.histo[-1] and self.macd.histo[-1] < \
                    self.macd.histo[-2] and self.macd.histo[-2] < 0:
                self.criticalBuyK = self.datas[0].high[0]
                find = True

        if self.macd.macd[0] > 0 and self.macd.macd[-1] < 0 and self.macd.macd[-2] < self.macd.macd[-1]:
            curIdx = 0
            adjacentUnderpants = False
            while self.macd.histo[curIdx] >= 0:
                if self.macd.macd[curIdx] <= 0 and self.macd.macd[curIdx - 1] >= 0:
                    adjacentUnderpants = True
                    break
                curIdx -= 1
            if not adjacentUnderpants:
                while self.macd.histo[curIdx] < 0:
                    if self.macd.macd[curIdx] <= 0 and self.macd.macd[curIdx - 1] >= 0:
                        adjacentUnderpants = True
                        break
                    curIdx -= 1
            if adjacentUnderpants:
                self.criticalBuyK = self.datas[0].high[0]
                find = True
        willOpt = OperateType.UNKNOWN

        if not self.position:
            if self.criticalBuyK and self.macd.macd[0] > 0 and not find:
                if self.datas[0].close[0] > self.datas[0].open[0] and self.datas[0].close[0] > self.criticalBuyK:
                    willOpt = OperateType.BUY

        else:
            if self.stopLossPoint:
                if self.dataclose[0] < self.stopLossPoint:
                    willOpt = OperateType.SELL

            if willOpt == OperateType.UNKNOWN:
                if self.data.low[0] < midBand:
                    willOpt = OperateType.SELL

            if willOpt == OperateType.UNKNOWN:
                if self.macd.histo[0] < self.macd.histo[-1] and self.macd.histo[-1] > self.macd.histo[-2] and \
                        self.macd.histo[-2] > 0:
                    self.criticalSellK = self.datas[0].low[0]
                elif self.criticalSellK and self.datas[0].close[0] < self.datas[0].open[0] and self.datas[0].close[
                    0] < self.criticalSellK:
                    willOpt = OperateType.SELL

        return willOpt

def shihunMacdRsiBollingerBand(main=False,commission=0.001,atr=True):
    node = Node(ShihunMacdRsiBollingerBandStrategy, main, commission, atr)
    node.start()

if __name__ == '__main__':
    shihunMacdRsiBollingerBand(True)