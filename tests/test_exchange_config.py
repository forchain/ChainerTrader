from trader.exchange.driver import ExchangeDriverType
from trader.exchange.exchange_config import ExchangeConfig, parse_exchange_config
from trader.exchange.exchange_type import ExchangeType


def test_parse_exchange_config_defaults_to_ccxt_driver():
    cfg = parse_exchange_config('{"ty":"BINANCE","api_key":"k","api_secret":"s"}')
    assert cfg.ty == ExchangeType.BINANCE
    assert cfg.driver == ExchangeDriverType.CCXT


def test_exchange_config_model_defaults_to_ccxt_driver():
    cfg = ExchangeConfig(ty=ExchangeType.BINANCE)
    assert cfg.driver == ExchangeDriverType.CCXT
