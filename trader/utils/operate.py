from datetime import datetime
from enum import Enum

from trader.utils.symbol_interval import SymbolInterval


class OperateType(Enum):
    UNKNOWN = 0
    BUY = 1
    SELL = 2

class Operate:
    def __init__(self,otype:OperateType,si:SymbolInterval,dtime:int):
        self.otype=otype
        self.symbol_interval=si
        self.dtime=dtime

    def to_dict(self):
        return {
            "type":self.otype.name,
            "symbol":self.symbol_interval.symbol,
            "interval":self.symbol_interval.interval.value,
            "datetime":datetime.fromtimestamp(self.dtime)
        }