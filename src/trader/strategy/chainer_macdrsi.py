from __future__ import absolute_import, division, print_function, unicode_literals

import backtrader as bt

from trader.strategy.base_strategy import BaseStrategy


# ChainerMacdrsi strategy
class ChainerMacdrsiStrategy(BaseStrategy):
    params = (
        ("overbought", 70),
        ("oversold", 30),
        ("chainer_auto_signal", True),
    )

    def __init__(self):
        super().__init__()

        self.macd = bt.indicators.MACDHisto(self.datas[0])
        self.rsi = bt.indicators.RSI(self.datas[0], period=self.params.period)

        self.macd_line = self.macd.macd
        self.signal_line = self.macd.signal


    def get_entry_signal(self) -> bool:
        if not self.can_trade():
            return False

        return self.macd_line[0] > self.signal_line[0] and self.rsi[0] < self.params.oversold


    def get_exit_signal(self) -> bool:
        if not self.can_trade():
            return False

        return self.macd_line[0] < self.signal_line[0] and self.rsi[0] > self.params.overbought