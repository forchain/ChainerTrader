from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from trader.common.config import DEFAULT_PERIOD
from trader.strategy.base_strategy import BaseStrategy
from trader.utils.kdj import KDJIndicator
from trader.utils.operate import OperateType


class DeviationMACDStrategy(BaseStrategy):
    params = (
        ("confirm",5),
        ("range", 10)
    )

    def __init__(self):
        super().__init__()
        self.set_default_period(9)

    def next(self):
        super().next()
        if self.order:
            return

        willOpt = OperateType.UNKNOWN

        if willOpt == OperateType.SELL:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 卖单:{self.data.close[0]:.2f}')
            self.order = self.sell()

        elif willOpt == OperateType.BUY:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 买单:{self.data.close[0]:.2f}')
            self.order = self.buy()
            self.update_stop_loss_point()
