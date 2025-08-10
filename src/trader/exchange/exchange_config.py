from pydantic import BaseModel

from trader.exchange.exchange_type import ExchangeType, parse_ex_type


class ExchangeConfig(BaseModel):
    ty: ExchangeType = ExchangeType.BINANCE
    api_key: str = ""
    api_secret: str = ""


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
