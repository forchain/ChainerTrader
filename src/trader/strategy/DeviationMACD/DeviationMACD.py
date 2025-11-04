from __future__ import absolute_import, division, print_function, unicode_literals

import math
from collections import deque
from enum import Enum

import backtrader as bt

from trader.indicators.pivot_high import PivotHigh
from trader.indicators.pivot_low import PivotLow
from trader.strategy.base_strategy import BaseStrategy
from trader.utils.operate import OperateType


class Pivot:
    def __init__(self, price: float, macd: float, bar_idx: int):
        self.price = price
        self.macd = macd
        self.bar_idx = bar_idx


class SourceType(Enum):
    CLOSE = 0
    HIGH = 1
    LOW = 2


class DeviationMACDStrategy(BaseStrategy):
    params = (
        ("lookback", 20),
        ("maxpp", 10),
        ("dontconfirm", False),
        ("source", SourceType.CLOSE),  # close high low
        ("maxbars", 100),
    )

    def __init__(self):
        super().__init__()
        self.params.atrdist = 15
        self.set_default_period(12)
        self.macd_hist = bt.indicators.MACDHisto(self.data)

        self.ph = PivotHigh(self.get_pivot_source(), left=self.params.period, right=self.params.period)
        self.pl = PivotLow(self.get_pivot_source(), left=self.params.period, right=self.params.period)
        self.ph_pivots = deque(maxlen=self.params.maxpp)
        self.pl_pivots = deque(maxlen=self.params.maxpp)
        if self.params.dontconfirm:
            self.startpoint = 0
        else:
            self.startpoint = -1

    def get_pivot_source(self):
        if self.params.source == SourceType.CLOSE:
            return self.data.close
        elif self.params.source == SourceType.HIGH:
            return self.data.high
        else:
            return self.data.low

    def next(self):
        super().next()
        if self.order:
            return

        if not math.isnan(self.ph.middle_value()):
            self.ph_pivots.appendleft(
                Pivot(
                    self.ph.middle_value(),
                    self.macd_hist[self.ph.middle_idx()],
                    self.bar_idx() + self.ph.middle_idx(),
                )
            )
        if not math.isnan(self.pl.middle_value()):
            self.pl_pivots.appendleft(
                Pivot(
                    self.pl.middle_value(),
                    self.macd_hist[self.pl.middle_idx()],
                    self.bar_idx() + self.pl.middle_idx(),
                )
            )
        if not self.can_trade():
            return

        willOpt = OperateType.UNKNOWN

        if self.positive_regular_positive_hidden_divergence(True) or self.positive_regular_positive_hidden_divergence(False):
            willOpt = OperateType.BUY

        if self.negative_regular_negative_hidden_divergence(True) or self.negative_regular_negative_hidden_divergence(False):
            willOpt = OperateType.SELL

        price = self.data.close[0]
        if not self.position:
            if willOpt == OperateType.BUY:
                commission_info = self.broker.getcommissioninfo(self.data)
                cash = self.broker.getcash()
                size = int(cash / (price * (1 + commission_info.p.commission)))

                if size > 0:
                    self.order = self.buy(size=size)
                    self.log_info(f"Kline:{self.cur_datetime()}, 创建 买单:{self.data.close[0]:.2f}")
                    self.update_stop_loss_point()

        else:
            if willOpt == OperateType.SELL:
                self.log_info(f"Kline:{self.cur_datetime()}, 创建 卖单:{self.data.close[0]:.2f}")
                self.order = self.close()
            elif self.need_stop_loss():
                self.log_info(f"Kline:{self.cur_datetime()}, 创建 清单:{self.data.close[0]:.2f}")
                self.order = self.close()

    def positive_regular_positive_hidden_divergence(self, pr: bool) -> bool:
        if self.bar_idx() <= 5:
            return False

        if not self.params.dontconfirm and self.macd_hist[0] <= self.macd_hist[-1] and self.data.close[0] <= self.data.close[-1]:
            return False

        price = self.get_pivot_source()[self.startpoint]
        macdh = self.macd_hist[self.startpoint]
        for item in self.ph_pivots:
            leng = self.bar_idx() + self.ph.middle_idx() - item.bar_idx
            if leng > self.params.maxbars:
                break
            need = False
            if pr and macdh > item.macd and price < item.price:
                need = True
            elif (not pr) and macdh < item.macd and price > item.price:
                need = True
            if need:
                slope1 = (macdh - price) / (leng - self.startpoint)
                virtual_line1 = macdh - slope1
                slope2 = (self.data.close[self.startpoint] - self.data.close[-leng]) / (leng - self.startpoint)
                virtual_line2 = self.data.close[self.startpoint] - slope2
                arrived = True

                for y in range(1 + self.startpoint, leng - 1):
                    if self.macd_hist[-y] < virtual_line1 or self.data.close[-y] < virtual_line2:
                        arrived = False
                        break
                    virtual_line1 = virtual_line1 - slope1
                    virtual_line2 = virtual_line2 - slope2

                if arrived:
                    return True

        return False

    def negative_regular_negative_hidden_divergence(self, pr: bool) -> bool:
        if self.bar_idx() <= 5:
            return False

        if not self.params.dontconfirm and self.macd_hist[0] >= self.macd_hist[-1] and self.data.close[0] >= self.data.close[-1]:
            return False

        price = self.get_pivot_source()[self.startpoint]
        macdh = self.macd_hist[self.startpoint]
        for item in self.pl_pivots:
            leng = self.bar_idx() + self.pl.middle_idx() - item.bar_idx
            if leng > self.params.maxbars:
                break
            need = False
            if pr and macdh < item.macd and price > item.price:
                need = True
            elif (not pr) and macdh > item.macd and price < item.price:
                need = True
            if need:

                slope1 = (macdh - price) / (leng - self.startpoint)
                virtual_line1 = macdh - slope1
                slope2 = (self.data.close[self.startpoint] - self.data.close[-leng]) / (leng - self.startpoint)
                virtual_line2 = self.data.close[self.startpoint] - slope2
                arrived = True

                for y in range(1 + self.startpoint, leng - 1):
                    if self.macd_hist[-y] > virtual_line1 or self.data.close[-y] > virtual_line2:
                        arrived = False
                        break
                    virtual_line1 = virtual_line1 - slope1
                    virtual_line2 = virtual_line2 - slope2

                if arrived:
                    return True

        return False
