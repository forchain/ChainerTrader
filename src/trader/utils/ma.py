from enum import Enum

class MAType(Enum):
    """Moving Average Types"""
    ALMA = 'ALMA'
    HMA = 'HMA'
    SMA = 'SMA'
    SWMA = 'SWMA'
    VWMA = 'VWMA'
    WMA = 'WMA'
    ZLEMA = 'ZLEMA'
    EMA = 'EMA'