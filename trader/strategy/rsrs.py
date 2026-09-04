from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt
from trader.strategy.base_strategy import BaseStrategy
from trader.utils.kdj import KDJIndicator
from trader.utils.operate import OperateType
from trader.utils.rsrs import RSRSIndicator


class RSRSStrategy(BaseStrategy):
    params = (
        ('period', 15),
        ('std_period', 500)
    )

    def __init__(self):
        super().__init__()
        self.rsrs = RSRSIndicator(self.data, period=self.params.period, std_period=self.params.std_period)

    def next(self):
        super().next()
        if self.order:
            return

        willOpt = OperateType.UNKNOWN

        if not self.position:
            if self.rsrs.zscore[0] > 1:
                willOpt = OperateType.BUY

        else:
            if self.need_stop_loss():
                willOpt = OperateType.SELL
            else:
                if self.rsrs.zscore[0] < 0:
                    willOpt = OperateType.SELL


        if willOpt == OperateType.SELL:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 卖单:{self.data.close[0]:.2f}')
            self.order = self.sell()

        elif willOpt == OperateType.BUY:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 买单:{self.data.close[0]:.2f}')
            self.order = self.buy()
            self.update_stop_loss_point()
