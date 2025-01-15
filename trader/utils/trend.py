
from enum import Enum

class TrendType(Enum):
    NORMAL = 0
    UP = 1
    DOWN = 2

def parseTrendType(name):
    if name == TrendType.NORMAL.name:
        return TrendType.NORMAL
    elif name == TrendType.UP.name:
        return TrendType.UP
    elif name == TrendType.DOWN.name:
        return TrendType.DOWN
    return TrendType.NORMAL