from datetime import datetime
from enum import Enum

from trader.utils.symbol_interval import SymbolInterval


class OperateType(Enum):
    UNKNOWN = 0
    BUY = 1
    SELL = 2


class Operate:
    def __init__(self, otype: OperateType, si: SymbolInterval, dtime: int, price=0):
        self.otype = otype
        self.symbol_interval = si
        self.dtime = dtime
        self.price = price

    def to_dict(self):
        return {
            "type": self.otype.name if self.otype else "UNKNOWN",
            "symbol": self.symbol_interval.symbol if self.symbol_interval else "",
            "interval": self.symbol_interval.interval.value if self.symbol_interval else 0,
            "datetime": f"{datetime.fromtimestamp(self.dtime)}" if self.dtime else "",
            "price": self.price if self.price is not None else 0.0,
        }
