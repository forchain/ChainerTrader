from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from trader.strategy.base_strategy import BaseStrategy
from trader.utils.inflectionpoint import InflectionType
from trader.utils.trend import TrendType


# trilogy basic framework strategy
class TrilogyStrategy(BaseStrategy):
    def __init__(self):
        super().__init__()

    def canBuy(self):
        """canBuy
        Can buy based on the current framework
        """
        # We only operate when it's a bullish candlestick
        if self.datas[0].close[0] <= self.datas[0].open[0]:
            return False

        # Current trend judgment
        minK = 3
        l = len(self.datas[0].close)
        if l <= minK:
            return False
        curTrend = TrendType.NORMAL

        av1=(self.datas[0].open[-1] + self.datas[0].close[-1]) / 2

        if self.datas[0].close[0] <= av1:
            curTrend=TrendType.DOWN
        elif self.datas[0].close[0] >= av1:
            curTrend=TrendType.UP
        else:
            curTrend = TrendType.NORMAL
        # We only operate in an upward trend
        if curTrend != TrendType.UP:
            return False
        # Identify all turning points
        infPoints = self.getInflectionPoints()
        if infPoints is None:
            return False
        if infPoints[0][1] == InflectionType.LOW:
            # Breaking through the previous high point and forming an upward trend
            if self.datas[0].close[0] > infPoints[1][2]:
                # The process of bottoming no longer breaks through
                if infPoints[0][2] < infPoints[1][2] and infPoints[0][2] > infPoints[2][2] and infPoints[0][2] > infPoints[3][2]:
                    return True

        return False

    def canSell(self):
        """canSell
        Can sell based on the current framework
        """
        if self.need_stop_loss():
            return True
        return False


    def getInflectionPoints(self):
        minK = 5
        l = len(self.datas[0].close)
        if l <= minK:
            return None

        band=5
        points = []
        index = -2
        high = 0
        low = 0
        while index > -l and len(points) <= band:
            av_0 = (self.datas[0].open[index-2] + self.datas[0].close[index-2]) / 2
            av_1 = (self.datas[0].open[index-1] + self.datas[0].close[index-1]) / 2
            av_2 = (self.datas[0].open[index] + self.datas[0].close[index]) / 2
            av_3 = (self.datas[0].open[index+1] + self.datas[0].close[index+1]) / 2
            av_4 = (self.datas[0].open[index+2] + self.datas[0].close[index+2]) / 2
            if av_0 < av_1 and av_1 < av_2 and av_2 > av_3 and av_3 > av_4:
                points.append((index,InflectionType.HIGH,av_2))
                high+=1
            elif av_0 > av_1 and av_1 > av_2 and av_2 < av_3 and av_3 < av_4:
                points.append((index,InflectionType.LOW,av_2))
                low+=1
            index-=1
        if high < 2 or low < 2:
            return None

        # Perform legitimacy checks on the generated data
        i = 0
        for point in points:
            if i == 0:
                i+=1
                continue
            if point[1] == InflectionType.HIGH and points[i-1][1] != InflectionType.LOW:
                return None
            if point[1] == InflectionType.LOW and points[i-1][1] != InflectionType.HIGH:
                return None
            i += 1

        return points

    def buy(self):
        """buy
            Process buy
        """
        self.update_stop_loss_point()
        super().buy()

    def sell(self):
        """sell
        Can sell based on the current framework
        """
        super().sell()