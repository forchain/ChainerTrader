from trader.core.exchange.domain import ExchangeConfig, ExchangeDriverType, ExchangeType, parse_exchange_config


def test_parse_exchange_config_defaults_to_ccxt_driver():
    cfg = parse_exchange_config('{"ty":"BINANCE","api_key":"k","api_secret":"s"}')
    assert cfg.ty == ExchangeType.BINANCE
    assert cfg.driver == ExchangeDriverType.CCXT


def test_exchange_config_model_defaults_to_ccxt_driver():
    cfg = ExchangeConfig(ty=ExchangeType.BINANCE)
    assert cfg.driver == ExchangeDriverType.CCXT


def test_parse_exchange_config_preserves_ccxt_http_proxy():
    cfg = parse_exchange_config('{"ty":"BINANCE","driver":"ccxt","http_proxy":"http://127.0.0.1:7890"}')
    assert cfg.http_proxy == "http://127.0.0.1:7890"
