from enum import Enum

class StrategyType(Enum):
    ShihunMACD = 0        # MACD from ShiHun
    ShihunRSI = 1         # RSI from ShiHun
    ShihunMACD2 = 2       # MACD2 from ShiHun
    ShihunRSI2 = 3        # RSI2 from ShiHun
    ShihunMACDRISBB = 4   # MACD + RSI + BollingerBand from ShiHun
    ShihunMACDRSIBBUP = 5 # MACD + RSI + BollingerBand from ShiHun only in the upward trend

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
    elif name == StrategyType.ShihunMACDRSIBBUP.name:
        return StrategyType.ShihunMACDRSIBBUP

    return None