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

        else:
            if willOpt == OperateType.SELL:
                self.log_info(f"Kline:{self.cur_datetime()}, 创建 卖单:{self.data.close[0]:.2f}")
                self.order = self.close()

    def _check_divergence(
        self,
        is_bullish: bool,
        is_regular: bool,
    ) -> bool:
        """
        通用背离检测方法

        Args:
            is_bullish: True为看涨背离(使用高点pivots), False为看跌背离(使用低点pivots)
            is_regular: True为常规背离, False为隐藏背离

        Returns:
            是否检测到背离信号
        """
        # 最小bar数量检查
        if self.bar_idx() <= 5:
            return False

        price = self.get_pivot_source()[self.startpoint]
        macdh = self.macd_hist[self.startpoint]

        # 根据是看涨还是看跌选择不同的pivot列表和指标
        if is_bullish:
            pivots = self.ph_pivots
            middle_idx = self.ph.middle_idx()
            # 确认信号：价格和MACD都在上涨
            if not self.params.dontconfirm and self.macd_hist[0] <= self.macd_hist[-1] and self.data.close[0] <= self.data.close[-1]:
                return False
        else:
            pivots = self.pl_pivots
            middle_idx = self.pl.middle_idx()
            # 确认信号：价格和MACD都在下跌
            if not self.params.dontconfirm and self.macd_hist[0] >= self.macd_hist[-1] and self.data.close[0] >= self.data.close[-1]:
                return False

        # 遍历历史pivot点寻找背离
        for item in pivots:
            leng = self.bar_idx() + middle_idx - item.bar_idx
            if leng > self.params.maxbars:
                break

            # 检查是否满足背离条件
            divergence_detected = False
            if is_bullish:
                if is_regular:
                    # 看涨常规背离：价格创新低，MACD未创新低
                    divergence_detected = macdh > item.macd and price < item.price
                else:
                    # 看涨隐藏背离：价格未创新低，MACD创新低
                    divergence_detected = macdh < item.macd and price > item.price
            else:
                if is_regular:
                    # 看跌常规背离：价格创新高，MACD未创新高
                    divergence_detected = macdh < item.macd and price > item.price
                else:
                    # 看跌隐藏背离：价格未创新高，MACD创新高
                    divergence_detected = macdh > item.macd and price < item.price

            if not divergence_detected:
                continue

            # 计算连接当前点和历史pivot点的虚拟线
            slope_macd = (macdh - item.macd) / (leng - self.startpoint)
            slope_price = (price - item.price) / (leng - self.startpoint)
            virtual_macd = macdh - slope_macd
            virtual_price = price - slope_price

            # 验证两点之间的所有bar是否都在虚拟线之上/之下
            line_valid = True
            for y in range(1 + self.startpoint, leng - 1):
                if is_bullish:
                    # 看涨背离：所有点都应该在虚拟线之上
                    if self.macd_hist[-y] < virtual_macd or self.get_pivot_source()[-y] < virtual_price:
                        line_valid = False
                        break
                else:
                    # 看跌背离：所有点都应该在虚拟线之下
                    if self.macd_hist[-y] > virtual_macd or self.get_pivot_source()[-y] > virtual_price:
                        line_valid = False
                        break
                virtual_macd -= slope_macd
                virtual_price -= slope_price

            if line_valid:
                return True

        return False

    def positive_regular_positive_hidden_divergence(self, pr: bool) -> bool:
        """检测看涨背离（常规或隐藏）"""
        return self._check_divergence(is_bullish=True, is_regular=pr)

    def negative_regular_negative_hidden_divergence(self, pr: bool) -> bool:
        """检测看跌背离（常规或隐藏）"""
        return self._check_divergence(is_bullish=False, is_regular=pr)
