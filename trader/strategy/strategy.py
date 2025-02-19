from enum import Enum

from trader.strategy.boll_mean_reg import BollingerMeanRegStrategy
from trader.strategy.dualma import DualMovingAverageStrategy
from trader.strategy.dualthrust import DualThrustStrategy
from trader.strategy.grid import GridStrategy
from trader.strategy.macdrsi import MACDRSIStrategy
from trader.strategy.shihunmacd import ShihunMACDStrategy
from trader.strategy.shihunmacd2 import ShihunMACD2Strategy
from trader.strategy.shihunmacdrsibb import ShihunMacdRsiBollingerBandStrategy
from trader.strategy.shihunrsi import ShihunRSIStrategy
from trader.strategy.shihunrsi2 import ShihunRSI2Strategy
from trader.strategy.turtle import TurtleStrategy


class StrategyType(Enum):
    ShihunMACD = 0        # MACD from ShiHun
    ShihunRSI = 1         # RSI from ShiHun
    ShihunMACD2 = 2       # MACD2 from ShiHun
    ShihunRSI2 = 3        # RSI2 from ShiHun
    ShihunMACDRISBB = 4   # MACD + RSI + BollingerBand from ShiHun
    MACDRSI = 5           # MACD + RSI
    GRID = 6              # GRID
    BOLLMEANREG = 7       # Bollinger Bands Mean Regression Strategy
    TURTLE = 8            # Turtle: Richard Dennis and William Eckhardt
    DUALMA = 9            # Dual Moving Average Crossover Strategy
    DUALTHRUST = 10       # Dual thrust strategy

def parseStrategyType(name):
    if name == StrategyType.ShihunMACD.name:
        return StrategyType.ShihunMACD
    elif name == StrategyType.ShihunRSI.name:
        return StrategyType.ShihunRSI
    elif name == StrategyType.ShihunMACD2.name:
        return StrategyType.ShihunMACD2
    elif name == StrategyType.ShihunRSI2.name:
        return StrategyType.ShihunRSI2
    elif name == StrategyType.ShihunMACDRISBB.name:
        return StrategyType.ShihunMACDRISBB
    elif name == StrategyType.MACDRSI.name:
        return StrategyType.MACDRSI
    elif name == StrategyType.GRID.name:
        return StrategyType.GRID
    elif name == StrategyType.BOLLMEANREG.name:
        return StrategyType.BOLLMEANREG
    elif name == StrategyType.TURTLE.name:
        return StrategyType.TURTLE
    elif name == StrategyType.DUALMA.name:
        return StrategyType.DUALMA
    elif name == StrategyType.DUALTHRUST.name:
        return StrategyType.DUALTHRUST
    return None

def parseStrategy(stype):
    if stype == StrategyType.ShihunMACD:
        return ShihunMACDStrategy

    elif stype == StrategyType.ShihunRSI:
        return ShihunRSIStrategy

    elif stype == StrategyType.ShihunMACD2:
        return ShihunMACD2Strategy

    elif stype == StrategyType.ShihunRSI2:
        return ShihunRSI2Strategy

    elif stype == StrategyType.ShihunMACDRISBB:
        return ShihunMacdRsiBollingerBandStrategy

    elif stype == StrategyType.MACDRSI:
        return MACDRSIStrategy

    elif stype == StrategyType.GRID:
        return GridStrategy

    elif stype == StrategyType.BOLLMEANREG:
        return BollingerMeanRegStrategy

    elif stype == StrategyType.TURTLE:
        return TurtleStrategy

    elif stype == StrategyType.DUALMA:
        return DualMovingAverageStrategy

    elif stype == StrategyType.DUALTHRUST:
        return DualThrustStrategy
    else:
        return None
