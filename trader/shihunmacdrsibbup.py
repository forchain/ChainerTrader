from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os.path
import sys

from backtrader import num2date

from trader.binance.csvdata import BinanceCSVData
from trader.node import Node
from trader.shihunmacdrsibb import ShihunMacdRsiBollingerBandStrategy
from trader.utils import path

import backtrader as bt

from trader.utils.chainerrsi import ChainerRSI, ChainerRSIHisto
from trader.utils.chainerstrategy import ChainerStrategy
from trader.utils.operate import OperateType
from trader.utils.trend import TrendType

def shihunMacdRsiBollingerBand(main=False,commission=0.001,atr=True):
    node = Node(ShihunMacdRsiBollingerBandStrategy, main, commission, atr,TrendType.UP)
    node.start()

if __name__ == '__main__':
    shihunMacdRsiBollingerBand(True)