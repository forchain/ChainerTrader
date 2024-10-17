from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import math

import backtrader as bt

class VolatilityAnalyzer(bt.Analyzer):
    params = (
        ('cerebro', None),
    )
    def __init__(self):
        self.returns = []
        self.last = self.params.cerebro.broker.getvalue()

    def next(self):
        if self.params.cerebro is None:
            return
        ret = (self.params.cerebro.broker.getvalue() / self.last)
        self.returns.append(ret)
        self.last = self.params.cerebro.broker.getvalue()

    def get_analysis(self):
        if self.params.cerebro is None:
            return 0
        volatility = bt.mathsupport.standarddev(self.returns)
        return volatility