from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from trader.strategy.base_strategy import BaseStrategy
from trader.utils.chainerrsi import ChainerRSIHisto
from trader.utils.operate import OperateType


# Shihun RSI strategy
class ShihunRSI2Strategy(BaseStrategy):
    params = (
        ('overbought', 70),
        ('oversold', 30),
    )

    def __init__(self):
        super().__init__()

        self.dataclose = self.datas[0].close

        self.order = None

        self.rsi = ChainerRSIHisto(self.datas[0])

        self.criticalBuyK = None
        self.criticalSellK = None

    def next(self):
        super().next()
        if self.order:
            return
        self.log_debug(f'Kline:{self.cur_datetime()} 收盘价, {self.dataclose[0]:.2f}')

        # find criticalK
        find = False
        if self.rsi.signal[0] > 50:
            if  self.rsi.histo[0] > 0 and self.rsi.histo[0] > self.rsi.histo[-1] and self.rsi.histo[-1] > self.rsi.histo[-2] and self.rsi.histo[-2] < 0:
                find=True
            if self.rsi.rsi[0] > self.params.overbought:
                find=True

            if self.rsi.signal[-1] < 50 and self.rsi.signal[-2] < self.rsi.signal[-1]:
                curIdx = 0
                adjacentUnderpants = False
                while self.rsi.signal[curIdx] > self.rsi.signal[curIdx - 1]:
                    curIdx -= 1
                while self.rsi.signal[curIdx] < self.rsi.signal[curIdx - 1]:
                    if self.rsi.signal[curIdx] > 50:
                        adjacentUnderpants = True
                        break
                    curIdx -= 1
                if adjacentUnderpants:
                    find = True
            if find:
                if self.datas[0].close[0] > self.datas[0].open[0]:
                    self.criticalBuyK = self.datas[0].high[0]
                else:
                    find=False


        willOpt = OperateType.UNKNOWN

        if not self.position:
            if self.criticalBuyK and self.rsi.signal[0] > 50 and not find:
                if self.datas[0].close[0] > self.datas[0].open[0] and self.datas[0].close[0] > self.criticalBuyK:
                    willOpt = OperateType.BUY

        else:
            if self.need_stop_loss():
                willOpt = OperateType.SELL
            else:
                if self.rsi.rsi[0] < self.params.oversold:
                    willOpt = OperateType.SELL
                if self.rsi.histo[0] < self.rsi.histo[-1] and self.rsi.histo[-1] < self.rsi.histo[-2] and \
                        self.rsi.histo[-2] > 0 and self.rsi.histo[0] < 0:
                    willOpt = OperateType.SELL



        if willOpt == OperateType.SELL:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 卖单:{self.dataclose[0]:.2f}')
            self.order = self.sell()
            self.criticalBuyK = None
            self.criticalSellK = None

        elif willOpt == OperateType.BUY:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 买单:{self.dataclose[0]:.2f}')
            self.order = self.buy()
            self.update_stop_loss_point()
            self.criticalBuyK = None
            self.criticalSellK = None
