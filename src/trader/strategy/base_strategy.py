from __future__ import absolute_import, division, print_function, unicode_literals

from datetime import datetime

import backtrader as bt
from backtrader import num2date

from trader.common.config import DEFAULT_PERIOD
from trader.common.log_tag import LogTag
from trader.utils.trend import TrendType


# chainer basic framework strategy
class BaseStrategy(bt.Strategy):
    params = (
        ("name", "Unkown"),
        ("atr", False),
        ("atrperiod", 14),
        ("atrdist", 5),  # ATR distance for stop price
        ("mode", TrendType.NORMAL),
        ("period", DEFAULT_PERIOD),
        ("log", None),
        ("stoploss", False),
        ("takeprofit", False),
        ("position", 0),
        ("trader", False),
    )

    def __init__(self):
        super().__init__()
        self.order = None

        # Stop loss point
        if self.params.stoploss:
            self.stopLossPoint = 0

        # take profit
        if self.params.takeprofit:
            self.takeProfitPoint = 0

        # To set the stop price
        if self.params.atr:
            self.atr = bt.indicators.ATR(self.datas[0], period=self.params.atrperiod)

        self.start_time = datetime.fromtimestamp(0)
        self.end_time = datetime.fromtimestamp(0)

        self.total_bars = len(self.datas[0])

    def start(self):
        if self.params.position:
            # Note: Setting initial positions directly can cause issues with broker calculations
            # This feature is experimental and should be used with caution
            try:
                # Check if broker has cash set
                cash = self.broker.getcash()
                if cash > 0:
                    self.broker.positions[self.data] = bt.position.Position(size=self.params.position)
                    self.log_info(f"set first position:{self.params.position}")
                else:
                    self.log_info("Cannot set position without broker cash, skipping position initialization")
            except Exception as e:
                self.log_info(f"Failed to set initial position: {e}")

        self.log_info(f"start:total_bars={self.total_bars}")

    def next(self):
        cur = self.cur_datetime()
        if cur > self.end_time:
            self.end_time = cur
        if int(self.start_time.timestamp()) == 0:
            self.start_time = cur

        self.log_debug(f"Kline:{cur} 收盘价, {self.data.close[0]:.2f}")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log_info(f"买入, 价格: {order.executed.price:.2f}, 花费: {order.executed.value:.2f}, 手续费: {order.executed.comm:.2f}")

            else:  # Sell
                self.log_info(f"卖出, 价格: {order.executed.price:.2f}, 花费: {order.executed.value:.2f}, 手续费: {order.executed.comm:.2f}")

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log_info("Order Canceled/Margin/Rejected")

        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return

        self.log_info(f"营业利润, 毛利润: {trade.pnl:.2f}, 净利润: {trade.pnlcomm:.2f}")

    def log_info(self, msg):
        if self.params.log is None:
            print(msg)
            return
        self.params.log.info(f"{msg}, [{self.name()}][{self.bar_idx()}/{self.total_bars-1}]", LogTag.STRATEGY)

    def log_debug(self, msg):
        if self.params.log is None:
            print(msg)
            return
        self.params.log.debug(f"{msg}, [{self.name()}][{self.bar_idx()}/{self.total_bars-1}]", LogTag.STRATEGY)

    def cur_datetime(self):
        return num2date(self.datas[0].datetime[0])

    def bar_idx(self):
        return len(self) - 1

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

    def update_takeprofit_point(self):
        if not self.params.takeprofit:
            return

        pdist = 0
        if self.params.atr:
            pdist = self.atr[0] * self.params.atrdist
        self.takeProfitPoint = self.datas[0].close[0] + pdist

    def name(self):
        return self.params.name

    def set_default_period(self, period):
        if self.params.period == DEFAULT_PERIOD:
            self.params.period = period

    def can_trade(self):
        if self.params.trader:
            if self.bar_idx() + 2 >= self.total_bars:
                return True
            return False
        return True
