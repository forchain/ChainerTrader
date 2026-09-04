from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from datetime import datetime

import backtrader as bt

from trader.utils.trend import TrendType
from backtrader import num2date

# chainer basic framework strategy
class BaseStrategy(bt.Strategy):
    params = (
        ('atr', False),
        ('atrperiod', 14),
        ('atrdist', 5),  # ATR distance for stop price
        ('mode', TrendType.NORMAL),
        ('period', 14),
        ('log', None),
        ('stoploss', False),
    )

    def __init__(self):
        super().__init__()
        # Stop loss point
        if self.params.stoploss:
            self.stopLossPoint = 0

        # To set the stop price
        if self.params.atr:
            self.atr = bt.indicators.ATR(self.datas[0], period=self.params.atrperiod)

        self.start_time=datetime.fromtimestamp(0)
        self.end_time=datetime.fromtimestamp(0)

    def next(self):
        cur = self.cur_datetime()
        if cur > self.end_time:
            self.end_time=cur
        if int(self.start_time.timestamp()) == 0:
            self.start_time=cur


    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log_info(
                    '买入, 价格: %.2f, 花费: %.2f, 手续费: %.2f' %
                    (order.executed.price,
                     order.executed.value,
                     order.executed.comm))

            else:  # Sell
                self.log_info('卖出, 价格: %.2f, 花费: %.2f, 手续费: %.2f' %
                         (order.executed.price,
                          order.executed.value,
                          order.executed.comm))

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log_info('Order Canceled/Margin/Rejected')

        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return

        self.log_info('营业利润, 毛利润: %.2f, 净利润: %.2f' %
                 (trade.pnl, trade.pnlcomm))

    def log_info(self,msg):
        if self.params.log is None:
            print(msg)
            return
        self.params.log.info(msg)

    def log_debug(self,msg):
        if self.params.log is None:
            print(msg)
            return
        self.params.log.debug(msg)

    def cur_datetime(self):
        return num2date(self.datas[0].datetime[0])

    def need_stop_loss(self):
        if not self.params.stoploss:
            return False

        if self.data.close[0] < self.stopLossPoint:
            return True
        return False

    def update_stop_loss_point(self):
        if not self.params.stoploss:
            return

        pdist = 0
        if self.params.atr:
            pdist = self.atr[0] * self.params.atrdist
        self.stopLossPoint = self.datas[0].close[0] - pdist