from enum import Enum


class OperateType(Enum):
    UNKNOWN = 0
    BUY = 1
    SELL = 2


def parse_operate_type(name):
    if name is None:
        return OperateType.UNKNOWN

    if name == OperateType.UNKNOWN.name:
        return OperateType.UNKNOWN
    elif name == OperateType.BUY.name:
        return OperateType.BUY
    elif name == OperateType.SELL.name:
        return OperateType.SELL

    return OperateType.UNKNOWN


class Operate:
    def __init__(self, otype: OperateType, dtime: int, price: float = 0):
        self.otype = otype
        self.dtime = dtime
        self.price = price

    def to_dict(self):
        return {
            "type": self.otype.name if self.otype else "UNKNOWN",
            "datetime": self.dtime,
            "price": self.price if self.price is not None else 0.0,
        }


def parse_opts(parsed_list) -> list[Operate]:
    if not parsed_list:
        return []

    ret = []
    for opc in parsed_list:
        op = Operate(parse_operate_type(opc["type"]), opc["datetime"], opc["price"])
        ret.append(op)

    return ret
