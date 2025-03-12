from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt
from trader.strategy.base_strategy import BaseStrategy
from trader.utils.kdj import KDJIndicator
from trader.utils.operate import OperateType


class KDJStrategy(BaseStrategy):
    params = (
        ("smooth", 3),
        ("upper",80),
        ("lower",20)
    )

    def __init__(self):
        super().__init__()
        self.kdj = KDJIndicator(self.data, period=self.params.period, smooth=self.params.smooth)

    def next(self):
        super().next()
        if self.order:
            return

        willOpt = OperateType.UNKNOWN

        if not self.position:
            if self.kdj.K[0] > self.kdj.D[0] and self.kdj.J[0] > self.params.lower:
                willOpt = OperateType.BUY

        else:
            if self.need_stop_loss():
                willOpt = OperateType.SELL
            else:
                if self.kdj.K[0] < self.kdj.D[0] and self.kdj.J[0] < self.params.upper:
                    willOpt = OperateType.SELL


        if willOpt == OperateType.SELL:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 卖单:{self.data.close[0]:.2f}')
            self.order = self.sell()

        elif willOpt == OperateType.BUY:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 买单:{self.data.close[0]:.2f}')
            self.order = self.buy()
            self.update_stop_loss_point()
