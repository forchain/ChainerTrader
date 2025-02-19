from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt
from trader.strategy.base_strategy import BaseStrategy
from trader.utils.operate import OperateType


class DualThrustStrategy(BaseStrategy):
    params = (
        ("upper_track", 0.5),  # uppper track param
        ("lower_track", 0.5)  # lower track param
    )

    def __init__(self):
        super().__init__()

        self.order = None

        self.high = bt.indicators.Highest(self.data.high, period=self.params.period)
        self.low = bt.indicators.Lowest(self.data.low, period=self.params.period)
        self.open_price = self.data.open[-1]

    def next(self):
        super().next()
        if self.order:
            return
        if len(self.data) < self.params.period:
            return

        self.open_price = self.data.open[-1]

        price_range = self.high[0] - self.low[0]
        upper_bound = self.open_price + self.params.upper_track * price_range
        lower_bound = self.open_price - self.params.lower_track * price_range

        willOpt = OperateType.UNKNOWN

        if not self.position:
            if self.data.close[0] > upper_bound:
                willOpt = OperateType.BUY

        else:
            if self.need_stop_loss():
                willOpt = OperateType.SELL
            else:
                if self.data.close[0] < lower_bound:
                    willOpt = OperateType.SELL


        if willOpt == OperateType.SELL:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 卖单:{self.data.close[0]:.2f}')
            self.order = self.sell()

        elif willOpt == OperateType.BUY:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 买单:{self.data.close[0]:.2f}')
            self.order = self.buy()
            self.update_stop_loss_point()
