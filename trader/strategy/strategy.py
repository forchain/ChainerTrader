from enum import Enum

class StrategyType(Enum):
    ShihunMACD = 0
    ShihunRSI = 1
    ShihunMACD2 = 2
    ShihunRSI2 = 3
    ShihunMACDRISBB = 4
    ShihunMACDRSIBBUP = 5

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