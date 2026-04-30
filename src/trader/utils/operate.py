from enum import Enum


class OperateType(Enum):
    UNKNOWN = 0
    BUY = 1
    SELL = 2
    LONG = 3
    SHORT = 4
    CLOSE = 5
    RISK_UPDATE = 6


def parse_operate_type(name):
    if name is None:
        return OperateType.UNKNOWN

    if name == OperateType.UNKNOWN.name:
        return OperateType.UNKNOWN
    elif name == OperateType.BUY.name:
        return OperateType.BUY
    elif name == OperateType.SELL.name:
        return OperateType.SELL
    elif name == OperateType.LONG.name:
        return OperateType.LONG
    elif name == OperateType.SHORT.name:
        return OperateType.SHORT
    elif name == OperateType.CLOSE.name:
        return OperateType.CLOSE
    elif name == OperateType.RISK_UPDATE.name:
        return OperateType.RISK_UPDATE

    return OperateType.UNKNOWN


class Operate:
    def __init__(self, otype: OperateType, dtime: int, price: float = 0):
        self.otype = otype
        self.dtime = dtime
        self.price = price

    def to_dict(self):
        payload = {
            "type": self.otype.name if self.otype else "UNKNOWN",
            "datetime": self.dtime,
            "price": self.price if self.price is not None else 0.0,
        }
        for name in (
            "stop_loss",
            "take_profit",
            "risk_reward_ratio",
            "signal_event_id",
            "signal_number",
            "trigger_reason",
            "breakeven_old_stop",
            "breakeven_new_stop",
            "breakeven_step",
            "signal_metadata",
            "divergence_metadata",
            "framework_trade",
        ):
            if hasattr(self, name):
                payload[name] = getattr(self, name)
        return payload


def parse_opts(parsed_list) -> list[Operate]:
    if not parsed_list:
        return []

    ret = []
    for opc in parsed_list:
        op = Operate(parse_operate_type(opc["type"]), opc["datetime"], opc["price"])
        for name in (
            "stop_loss",
            "take_profit",
            "risk_reward_ratio",
            "signal_event_id",
            "signal_number",
            "trigger_reason",
            "breakeven_old_stop",
            "breakeven_new_stop",
            "breakeven_step",
            "signal_metadata",
            "divergence_metadata",
            "framework_trade",
        ):
            if name in opc:
                setattr(op, name, opc[name])
        ret.append(op)

    return ret
