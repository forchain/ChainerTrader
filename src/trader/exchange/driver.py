from __future__ import annotations

from enum import Enum


class ExchangeDriverType(str, Enum):
    CCXT = "ccxt"
    BINANCE_NATIVE = "binance_native"
