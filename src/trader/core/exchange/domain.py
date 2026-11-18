"""Exchange account domain: balances, views, open orders, configuration, and user context.

Pure data and rules for the exchange account bounded context. Position and
protection views are shared with execution, so they are re-exported here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel

from trader.core.execution.domain import PositionView, ProtectionOrderView

__all__ = [
    "Balance",
    "ExchangeConfig",
    "ExchangeDriverType",
    "ExchangeType",
    "MarginMode",
    "OpenOrder",
    "PositionView",
    "ProtectionOrderView",
    "UserExchangeContext",
    "parse_ex_type",
    "parse_exchange_config",
]


class MarginMode(str, Enum):
    SPOT = "spot"
    CROSS_MARGIN = "cross_margin"
    ISOLATED_MARGIN = "isolated_margin"


class ExchangeDriverType(str, Enum):
    CCXT = "ccxt"
    BINANCE_NATIVE = "binance_native"


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


class ExchangeConfig(BaseModel):
    ty: ExchangeType = ExchangeType.BINANCE
    driver: ExchangeDriverType = ExchangeDriverType.CCXT
    api_key: str = ""
    api_secret: str = ""
    # Legacy shared base path (kept for backward compatibility).
    base_path: str = ""
    # Optional explicit endpoints per trading path.
    spot_base_path: str = ""
    margin_base_path: str = ""
    # Optional CCXT REST HTTP proxy, e.g. http://127.0.0.1:7890.
    http_proxy: str = ""
    margin_mode: MarginMode = MarginMode.SPOT

    def with_margin_mode(self, margin_mode: MarginMode) -> "ExchangeConfig":
        if self.margin_mode == margin_mode:
            return self
        payload = self.model_dump()
        payload["margin_mode"] = margin_mode
        return ExchangeConfig(**payload)


def parse_exchange_config(cfg_data: str) -> ExchangeConfig | None:
    """Parse a JSON exchange config or a bare exchange name (e.g. "BINANCE")."""
    try:
        return ExchangeConfig.model_validate_json(cfg_data)
    except Exception:
        return ExchangeConfig(ty=parse_ex_type(cfg_data))


class Balance(BaseModel):
    asset: str = ""
    free: float = 0
    locked: float = 0
    max_borrowable: float = 0
    operable: float = 0


@dataclass(frozen=True)
class OpenOrder:
    symbol: str
    side: str
    quantity: float
    order_id: str
    order_type: str
    price: float
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "order_id": self.order_id,
            "order_type": self.order_type,
            "price": self.price,
            "status": self.status,
        }


@dataclass(frozen=True)
class UserExchangeContext:
    cfg: ExchangeConfig
    user_id: int
    credential_id: int | None
    masked_api_key: str
