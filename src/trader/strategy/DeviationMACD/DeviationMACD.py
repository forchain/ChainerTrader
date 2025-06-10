from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from trader.common.config import DEFAULT_PERIOD
from trader.strategy.base_strategy import BaseStrategy
from trader.utils.operate import OperateType
import backtrader as bt

class DeviationMACDStrategy(BaseStrategy):
    params = (
        ("lookback",20),
        ("range", 10)
    )

    def __init__(self):
        super().__init__()
        self.set_default_period(12)
        self.macd_hist = bt.indicators.MACDHisto(self.data)

        self.price_lows = []
        self.macd_lows = []
        self.price_highs = []
        self.macd_highs = []

    def next(self):
        super().next()
        if self.order:
            return

        willOpt = OperateType.UNKNOWN

        price = self.data.close[0]
        hist = self.macd_hist[0]

        if self.is_local_min(self.data.close, 2):
            self.price_lows.append(price)
            self.macd_lows.append(hist)
        if self.is_local_max(self.data.close, 2):
            self.price_highs.append(price)
            self.macd_highs.append(hist)

        self.price_lows = self.price_lows[-self.params.lookback:]
        self.macd_lows = self.macd_lows[-self.params.lookback:]
        self.price_highs = self.price_highs[-self.params.lookback:]
        self.macd_highs = self.macd_highs[-self.params.lookback:]

        if len(self.price_lows) >= 2 and len(self.macd_lows) >= 2:
            p1, p2 = self.price_lows[-2], self.price_lows[-1]
            m1, m2 = self.macd_lows[-2], self.macd_lows[-1]
            if p2 < p1 and m2 > m1:
                willOpt = OperateType.BUY

        if len(self.price_highs) >= 2 and len(self.macd_highs) >= 2:
            p1, p2 = self.price_highs[-2], self.price_highs[-1]
            m1, m2 = self.macd_highs[-2], self.macd_highs[-1]
            if p2 > p1 and m2 < m1:
                willOpt = OperateType.SELL


        if willOpt == OperateType.SELL:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 卖单:{self.data.close[0]:.2f}')
            self.order = self.sell()

        elif willOpt == OperateType.BUY:
            self.log_info(f'Kline:{self.cur_datetime()}, 创建 买单:{self.data.close[0]:.2f}')
            self.order = self.buy()
            self.update_stop_loss_point()

    def is_local_min(self, data, look=2):
        return data[-look] > data[-1] and data[0] < data[-1]

    def is_local_max(self, data, look=2):
        return data[-look] < data[-1] and data[0] > data[-1]