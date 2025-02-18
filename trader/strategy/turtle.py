from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt
from trader.strategy.base_strategy import BaseStrategy
from trader.utils.operate import OperateType


class TurtleStrategy(BaseStrategy):
    def __init__(self):
        super().__init__()
        self.params.period=20
        self.highest = bt.indicators.Highest(self.data.high, period=self.params.period)
        self.lowest = bt.indicators.Lowest(self.data.low, period=self.params.period)

    def next(self):
        super().next()

        if self.order:
            return

        willOpt = OperateType.UNKNOWN

        if not self.position:
            if self.data.close[0] > self.highest[0]:
               willOpt = OperateType.BUY
        else:
            if self.data.close[0] < self.lowest[0]:
               willOpt = OperateType.SELL
            elif self.need_stop_loss():
               willOpt = OperateType.SELL

        if willOpt == OperateType.SELL:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 卖单:{self.dataclose[0]:.2f}')
            self.order = self.sell()

        elif willOpt == OperateType.BUY:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 买单:{self.dataclose[0]:.2f}')
            self.order = self.buy()
            self.update_stop_loss_point()