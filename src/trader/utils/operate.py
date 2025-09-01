from datetime import datetime
from enum import Enum

from trader.utils.symbol_interval import SymbolInterval


class OperateType(Enum):
    UNKNOWN = 0
    BUY = 1
    SELL = 2


class Operate:
    def __init__(self, otype: OperateType, dtime: int, price=0):
        self.otype = otype
        self.dtime = dtime
        self.price = price

    def to_dict(self):
        return {
            "type": self.otype.name if self.otype else "UNKNOWN",
            "datetime": f"{datetime.fromtimestamp(self.dtime)}" if self.dtime else "",
            "price": self.price if self.price is not None else 0.0,
        }
