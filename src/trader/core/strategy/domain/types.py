"""Strategy value enums shared across the hexagonal layers."""

from enum import Enum


class InflectionType(Enum):
    HIGH = 1
    LOW = 2


class MAType(Enum):
    """Moving Average Types"""

    ALMA = "ALMA"
    HMA = "HMA"
    SMA = "SMA"
    SWMA = "SWMA"
    VWMA = "VWMA"
    WMA = "WMA"
    ZLEMA = "ZLEMA"
    EMA = "EMA"


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
