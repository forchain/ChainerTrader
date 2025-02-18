from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt

from trader.strategy.base_strategy import BaseStrategy
from trader.utils.chainerrsi import ChainerRSIHisto
from trader.utils.operate import OperateType
from trader.utils.trend import TrendType


# Shihun MACD RSI BollingerBand strategy
class ShihunMacdRsiBollingerBandStrategy(BaseStrategy):
    params = (
        ('devfactor', 2),       # 标准差系数
    )

    def __init__(self):
        super().__init__()
        self.params.period=20  # 布林带周期
        self.dataclose = self.datas[0].close

        self.order = None

        self.macd = bt.indicators.MACDHisto(self.datas[0])
        self.bollinger = bt.indicators.BollingerBands(
            self.datas[0].close,
            period=self.params.period,
            devfactor=self.params.devfactor
        )
        self.rsi = ChainerRSIHisto(self.datas[0])

        self.criticalBuyK = None
        self.criticalSellK = None

    def next(self):
        super().next()
        if self.order:
            return

        willOpt = OperateType.UNKNOWN
        curTrend = self.getTrend()

        if curTrend != TrendType.UP:
            if self.params.mode != TrendType.UP:
                willOpt = self.processShock()
        else:
            willOpt = self.processTrend()

        if willOpt == OperateType.SELL:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 卖单:{self.dataclose[0]:.2f}')
            self.order = self.sell()
            self.criticalBuyK = None
            self.criticalSellK = None

        elif willOpt == OperateType.BUY:
            self.order = self.buy()
            pdist = 0
            if curTrend == TrendType.UP:
                self.update_stop_loss_point()
            else:
                pdist = self.datas[0].low[0]
                if self.datas[0].low[-1] < pdist:
                    pdist = self.datas[0].low[-1]
            self.stopLossPoint = pdist
            self.criticalBuyK = None
            self.criticalSellK = None
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 买单:{self.dataclose[0]:.2f}, 止损点:{self.stopLossPoint:.2f}')

    def getTrend(self):
        if self.macd.macd[0] > 0:
            return TrendType.UP
        return TrendType.DOWN

    def processShock(self):
        upperBand = self.bollinger.lines.top[0]
        lowerBand = self.bollinger.lines.bot[0]
        midBand = self.bollinger.lines.mid[0]

        # find criticalK
        find = False
        if self.datas[0].close[0] < lowerBand and self.datas[0].close[0] > self.datas[0].open[0]:
            if self.macd.histo[0] < 0 and self.macd.histo[0] > self.macd.histo[-1] and self.macd.histo[-1] < self.macd.histo[-2]:
                find = True
            if self.rsi.histo[0] > 0 and self.rsi.histo[0] > self.rsi.histo[-1] and self.rsi.histo[-1] > self.rsi.histo[-2] and self.rsi.histo[-2] < 0:
                find = True
            if find:
                self.criticalBuyK = self.datas[0].high[0]

        willOpt = OperateType.UNKNOWN

        if not self.position:
            if self.criticalBuyK and self.macd.macd[0] > 0 and not find:
                if self.datas[0].close[0] > self.datas[0].open[0] and self.datas[0].close[0] > self.criticalBuyK:
                    willOpt = OperateType.BUY

        else:
            if self.need_stop_loss():
                willOpt = OperateType.SELL
            else:
                if self.datas[0].high[0] > upperBand:
                    willOpt = OperateType.SELL
                if self.datas[0].close[0] < midBand:
                    willOpt = OperateType.SELL
                if self.macd.histo[0] < self.macd.histo[-1] and self.macd.histo[-1] > self.macd.histo[-2] and \
                        self.macd.histo[-2] > 0:
                    willOpt = OperateType.SELL

                if self.rsi.histo[0] < 0 and self.rsi.histo[0] < self.rsi.histo[-1] and self.rsi.histo[-1] < \
                        self.rsi.histo[-2] and self.rsi.histo[-2] > 0:
                    willOpt = OperateType.SELL

        return willOpt

    def processTrend(self):
        upperBand = self.bollinger.lines.top[0]
        lowerBand = self.bollinger.lines.bot[0]
        midBand = self.bollinger.lines.mid[0]

        # find criticalK
        find = False
        if self.macd.macd[0] > 0 and self.data.close[0] > upperBand:
            if self.datas[0].close[0] > self.datas[0].open[0]:
                self.criticalBuyK = self.datas[0].high[0]
                find = True

        if self.macd.macd[0] > 0 and self.macd.macd[-1] < 0 and self.macd.macd[-2] < self.macd.macd[-1]:
            curIdx = 0
            adjacentUnderpants = False
            while self.macd.histo[curIdx] >= 0:
                if self.macd.macd[curIdx] <= 0 and self.macd.macd[curIdx - 1] >= 0:
                    adjacentUnderpants = True
                    break
                curIdx -= 1
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
                if self.data.low[0] < midBand:
                    willOpt = OperateType.SELL

            if self.macd.histo[0] < self.macd.histo[-1] and self.macd.histo[-1] > self.macd.histo[-2] and \
                    self.macd.histo[-2] > 0:
                willOpt = OperateType.SELL
            if self.criticalSellK and self.datas[0].close[0] < self.datas[0].open[0] and self.datas[0].close[
                0] < self.criticalSellK:
                willOpt = OperateType.SELL


        return willOpt
