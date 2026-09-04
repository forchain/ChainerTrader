from __future__ import annotations

from enum import Enum
from typing import Protocol


class ExchangeDriverType(str, Enum):
    CCXT = "ccxt"
    BINANCE_NATIVE = "binance_native"


class ExchangeDriver(Protocol):
    def driver_name(self) -> str: ...
