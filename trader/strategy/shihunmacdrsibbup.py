from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from trader.strategy.node import Node
from trader.strategy.shihunmacdrsibb import ShihunMacdRsiBollingerBandStrategy

from trader.utils.trend import TrendType

# Only operate in a market environment that follows the trend
def shihunMacdRsiBollingerBandUp(main=False,commission=0.001,atr=True):
    node = Node(ShihunMacdRsiBollingerBandStrategy, main, commission, atr,TrendType.UP)
    node.start()

if __name__ == '__main__':
    shihunMacdRsiBollingerBandUp(True)