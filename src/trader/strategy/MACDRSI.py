from __future__ import absolute_import, division, print_function, unicode_literals

import backtrader as bt

from trader.strategy.base_strategy import BaseStrategy
from trader.utils.operate import OperateType


# MACDRSI strategy
class MACDRSIStrategy(BaseStrategy):
    params = (
        ("overbought", 70),
        ("oversold", 30),
    )

    def __init__(self):
        super().__init__()

        self.dataclose = self.datas[0].close

        self.order = None

        self.macd = bt.indicators.MACDHisto(self.datas[0])
        self.rsi = bt.indicators.RSI(self.datas[0], period=self.params.period)

        self.macd_line = self.macd.macd
        self.signal_line = self.macd.signal

        self.position_type = None  # 'long' or 'short'

    def next(self):
        super().next()
        if self.order:
            return

        if not self.can_trade():
            return

        willOpt = OperateType.UNKNOWN
        up_macd = False
        down_macd = False
        if self.macd_line[0] > self.signal_line[0]:
            up_macd = True
        elif self.macd_line[0] < self.signal_line[0]:
            down_macd = True

        if not self.position or self.position.size == 0:
            if up_macd and self.rsi[0] < self.params.oversold:
                willOpt = OperateType.LONG

            if down_macd and self.rsi[0] > self.params.overbought:
                willOpt = OperateType.SHORT

        elif self.position.size > 0:
            if down_macd and self.rsi[0] > self.params.overbought:
                willOpt = OperateType.SHORT
            elif self.need_stop_loss():
                willOpt = OperateType.CLOSE

        elif self.position.size < 0:
            if up_macd and self.rsi[0] < self.params.overbought:
                willOpt = OperateType.LONG
            elif self.need_takeprofit():
                willOpt = OperateType.CLOSE

        if willOpt == OperateType.CLOSE:
            self.log_info(f"Kline:{self.cur_datetime()}, 平仓:{self.dataclose[0]:.2f}")
            self.order = self.close()

        elif willOpt == OperateType.LONG:
            if self.position and self.position.size < 0:
                self.log_info(f"Kline:{self.cur_datetime()}, 平空仓:{self.dataclose[0]:.2f}")
                self.order = self.close()
            else:
                self.log_info(f"Kline:{self.cur_datetime()}, 开多仓:{self.dataclose[0]:.2f}")
                self.order = self.buy()

        elif willOpt == OperateType.SHORT:
            if self.position and self.position.size > 0:
                self.log_info(f"Kline:{self.cur_datetime()}, 平多仓:{self.dataclose[0]:.2f}")
                self.order = self.close()
            else:
                self.log_info(f"Kline:{self.cur_datetime()}, 开空仓:{self.dataclose[0]:.2f}")
                self.order = self.sell()

