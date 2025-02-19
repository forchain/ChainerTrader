from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt
from trader.strategy.base_strategy import BaseStrategy
from trader.utils.operate import OperateType


class DualMovingAverageStrategy(BaseStrategy):
    params = (
        ("long_period", 50),
    )

    def __init__(self):
        super().__init__()

        self.order = None
        self.sma_short = bt.indicators.SimpleMovingAverage(self.data.close, period=self.params.period)
        self.sma_long = bt.indicators.SimpleMovingAverage(self.data.close, period=self.params.long_period)


    def next(self):
        super().next()
        if self.order:
            return
        if len(self.data) < self.params.long_period:
            return

        willOpt = OperateType.UNKNOWN

        if not self.position:
            if self.sma_short[0] > self.sma_long[0]:
                willOpt = OperateType.BUY

        else:
            if self.need_stop_loss():
                willOpt = OperateType.SELL
            else:
                if self.sma_short[0] < self.sma_long[0]:  # 短均线下穿长均线（卖出信号）
                    willOpt = OperateType.SELL


        if willOpt == OperateType.SELL:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 卖单:{self.data.close[0]:.2f}')
            self.order = self.sell()

        elif willOpt == OperateType.BUY:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 买单:{self.data.close[0]:.2f}')
            self.order = self.buy()
            self.update_stop_loss_point()
