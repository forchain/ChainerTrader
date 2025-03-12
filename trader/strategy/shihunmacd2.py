from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt

from trader.strategy.base_strategy import BaseStrategy
from trader.utils.operate import OperateType


# Shihun MACD strategy
class ShihunMACD2Strategy(BaseStrategy):

    def __init__(self):
        super().__init__()

        self.dataclose = self.datas[0].close

        self.order = None

        self.macd = bt.indicators.MACDHisto(self.datas[0])

        self.criticalBuyK = None
        self.criticalSellK = None

    def next(self):
        super().next()
        if self.order:
            return


        # find criticalK
        find = False
        if self.macd.macd[0] > 0 and self.macd.macd[-1] > 0 and self.macd.macd[-2] > 0:
            if  self.macd.histo[0] < 0 and self.macd.histo[0] > self.macd.histo[-1] and self.macd.histo[-1] < self.macd.histo[-2] and self.macd.histo[-2] < 0:
                self.criticalBuyK = self.datas[0].high[0]
                find=True

        if self.macd.macd[0] > 0 and self.macd.macd[-1] < 0 and self.macd.macd[-2] < self.macd.macd[-1]:
            curIdx = 0
            adjacentUnderpants = False
            while self.macd.histo[curIdx] >= 0:
                if self.macd.macd[curIdx] <= 0 and self.macd.macd[curIdx-1] >= 0:
                    adjacentUnderpants=True
                    break
                curIdx-=1
            if not adjacentUnderpants:
                while self.macd.histo[curIdx] < 0:
                    if self.macd.macd[curIdx] <= 0 and self.macd.macd[curIdx - 1] >= 0:
                        adjacentUnderpants = True
                        break
                    curIdx -= 1
            if adjacentUnderpants:
                self.criticalBuyK = self.datas[0].high[0]
                find = True

        willOpt = OperateType.UNKNOWN

        if not self.position:
            if self.criticalBuyK and self.macd.macd[0] > 0 and not find:
                if self.datas[0].close[0] > self.datas[0].open[0] and self.datas[0].close[0] > self.criticalBuyK:
                    willOpt = OperateType.BUY

        else:
            if self.need_stop_loss():
                   willOpt = OperateType.SELL
            else:
                if willOpt == OperateType.UNKNOWN:
                    if self.macd.histo[0] < self.macd.histo[-1] and self.macd.histo[-1] > self.macd.histo[-2] and \
                            self.macd.histo[-2] > 0:
                        self.criticalSellK = self.datas[0].low[0]
                    elif self.criticalSellK and self.datas[0].close[0] < self.datas[0].open[0] and self.datas[0].close[
                        0] < self.criticalSellK:
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
