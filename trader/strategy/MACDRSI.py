from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt
from mypyc.ir.ops import Float

from trader.strategy.base_strategy import BaseStrategy
from trader.utils.operate import OperateType


# MACDRSI strategy
class MACDRSIStrategy(BaseStrategy):
    params = (
        ('overbought', 70),
        ('oversold', 30),
    )

    def __init__(self):
        super().__init__()

        self.dataclose = self.datas[0].close

        self.order = None

        self.macd = bt.indicators.MACDHisto(self.datas[0])
        self.rsi = bt.indicators.RSI(self.datas[0], period=self.params.period)

        self.macd_line = self.macd.macd
        self.signal_line = self.macd.signal

        self.up_macd = False
        self.down_macd = False


    def next(self):
        super().next()
        if self.order:
            return

        willOpt = OperateType.UNKNOWN

        if not self.position:
            if not self.up_macd:
                if self.macd_line[0] > self.signal_line[0]:
                    self.up_macd=True

            if self.up_macd and self.rsi[0] < self.params.oversold:
                willOpt = OperateType.BUY
        else:
            if not self.down_macd:
                if self.macd_line[0] < self.signal_line[0]:
                    self.down_macd=True

            if self.need_stop_loss():
                willOpt = OperateType.SELL
            else:
                if self.down_macd and self.rsi[0] > self.params.overbought:
                    willOpt = OperateType.SELL


        if willOpt == OperateType.SELL:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 卖单:{self.dataclose[0]:.2f}')
            self.order = self.sell()
            self.down_macd=False
            self.up_macd=False

        elif willOpt == OperateType.BUY:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 买单:{self.dataclose[0]:.2f}')
            self.order = self.buy()
            self.update_stop_loss_point()
            self.down_macd = False
            self.up_macd = False
