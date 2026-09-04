from enum import Enum
from pydantic import BaseModel

from trader.exchange.driver import ExchangeDriverType
from trader.exchange.exchange_type import ExchangeType, parse_ex_type


class MarginMode(str, Enum):
    SPOT = "spot"
    CROSS_MARGIN = "cross_margin"
    ISOLATED_MARGIN = "isolated_margin"


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
    margin_mode: MarginMode = MarginMode.SPOT

    def with_margin_mode(self, margin_mode: MarginMode) -> "ExchangeConfig":
        if self.margin_mode == margin_mode:
            return self
        payload = self.model_dump()
        payload["margin_mode"] = margin_mode
        return ExchangeConfig(**payload)


# '{"ty": "BINANCE", "api_key": "","api_secret":""}'
# or
# "BINANCE"
def parse_exchange_config(cfg_data: str) -> ExchangeConfig | None:
    ex_cfg = None
    try:
        ex_cfg = ExchangeConfig.model_validate_json(cfg_data)
    except Exception:
        ex_cfg = ExchangeConfig(ty=parse_ex_type(cfg_data))
    return ex_cfg
