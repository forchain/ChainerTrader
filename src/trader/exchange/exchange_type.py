from enum import Enum


class ExchangeType(Enum):
    BINANCE = "BINANCE"
    COINBASE = "COINBASE"
    OKX = "OKX"


def parse_ex_type(name):
    if name == ExchangeType.BINANCE.name:
        return ExchangeType.BINANCE
    elif name == ExchangeType.COINBASE.name:
        return ExchangeType.COINBASE
    elif name == ExchangeType.OKX.name:
        return ExchangeType.OKX
    return None
