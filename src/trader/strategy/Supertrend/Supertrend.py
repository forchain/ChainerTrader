from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from trader.strategy.base_strategy import BaseStrategy

class SupertrendStrategy(BaseStrategy):

    def __init__(self):
        super().__init__()

    def next(self):
        super().next()
        if self.order:
            return