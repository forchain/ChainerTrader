from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os.path
import sys

from backtrader import num2date

from trader.binance.csvdata import BinanceCSVData
from trader.utils import path

import backtrader as bt
import backtrader.analyzers as btanalyzers

from prettytable import PrettyTable

from trader.utils.operate import OperateType


# Shihun MACD strategy
class ShihunMACDStrategy(bt.Strategy):
    params = (
        ('atrperiod', 14),
        ('atrdist', 5),  # ATR distance for stop price
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

        self.macd = bt.indicators.MACDHisto(self.datas[0])

        # Stop loss point
        self.stopLossPoint=0
        # To set the stop price
        self.atr = bt.indicators.ATR(self.datas[0], period=self.params.atrperiod)

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
        if self.macd.macd[0] > 0 and self.macd.macd[-1] > 0 and self.macd.macd[-2] > 0:
            if  self.macd.histo[0] < 0 and self.macd.histo[0] > self.macd.histo[-1] and self.macd.histo[-1] < self.macd.histo[-2] and self.macd.histo[-2] < 0:
                self.criticalBuyK = self.datas[0].high[0]
                find=True

        if self.macd.macd[0] > 0 and self.macd.macd[-1] < 0 and self.macd.macd[-2] < self.macd.macd[-1]:
            curIdx = 0
            adjacentUnderpants = False
            while self.macd.histo[curIdx] >= 0:
                if self.macd.macd[curIdx] <= 0 and self.macd.macd[curIdx-1] >= 0:
                    adjacentUnderpants=True
                    break
                curIdx-=1
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
                    if self.macd.histo[0] < self.macd.histo[-1] and self.macd.histo[-1] > self.macd.histo[-2] and self.macd.histo[-2] > 0:
                        self.criticalSellK = self.datas[0].low[0]
                    elif self.criticalSellK and self.datas[0].close[0] < self.datas[0].open[0] and self.datas[0].close[0] < self.criticalSellK:
                        willOpt = OperateType.SELL


        if willOpt == OperateType.SELL:
            self.log('收盘价: %.2f (创建 卖单)' % self.dataclose[0])
            self.order = self.sell()
            self.criticalBuyK = None
            self.criticalSellK = None

        elif willOpt == OperateType.BUY:
            self.log('收盘价: %.2f (创建 买单)' % self.dataclose[0])
            self.order = self.buy()
            pdist = self.atr[0] * self.params.atrdist
            self.stopLossPoint = self.datas[0].close[0] - pdist
            self.criticalBuyK = None
            self.criticalSellK = None


def shihunMACD(main=False,commission=0.001):
    cerebro = bt.Cerebro()

    cerebro.addstrategy(ShihunMACDStrategy)
    cerebro.addanalyzer(btanalyzers.SharpeRatio, _name='sharpeRatio')
    cerebro.addanalyzer(btanalyzers.DrawDown, _name="drawdown")

    datapath = os.path.join(path.GetDatasDir(), 'ETHUSDT-1h-202301-202401.csv')

    data = BinanceCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2023, 1, 1),
        todate=datetime.datetime(2024, 1, 1),
    )

    cerebro.adddata(data)
    initialCash = 100000
    cerebro.broker.setcash(initialCash)

    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    cerebro.broker.setcommission(commission=commission)

    rets=cerebro.run()
    ret = rets[0]

    finalFund = cerebro.broker.getvalue()
    sharpeRatio = ret.analyzers.sharpeRatio.get_analysis()
    totalReturnRate = (finalFund - initialCash) / initialCash * 100

    drawdown = ret.analyzers.drawdown.get_analysis()
    maxDrawdown = drawdown.max.drawdown
    maxDrawdownDuration = drawdown.max.len

    if main:
        cerebro.plot()

    # statistics
    table = PrettyTable()
    table.field_names = ["Name", "Value"]
    table.add_row(["手续费率", commission])
    table.add_row(["初始资金", format(initialCash, '.2f')])
    table.add_row(["最终资金", format(finalFund, '.2f')])
    table.add_row(["总收益率", format(totalReturnRate, '.2f')+"%"])
    table.add_row(["夏普比率", format(sharpeRatio['sharperatio'],'.2f')])
    table.add_row(["最大回撤:",(f"{maxDrawdown:.2f}%")])
    table.add_row(["最大回撤持续时间:", (f"{maxDrawdownDuration:.2f}")])

    print("\n")
    print(table)


if __name__ == '__main__':
    shihunMACD(True)