from trader.core.exchange.domain import ExchangeConfig, ExchangeDriverType, ExchangeType, MarginMode, parse_exchange_config


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


def test_exchange_config_to_dict_round_trips_through_parse_exchange_config():
    import json

    original = ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.BINANCE_NATIVE, api_key="k", margin_mode=MarginMode.CROSS_MARGIN)

    restored = parse_exchange_config(json.dumps({key: getattr(value, "value", value) for key, value in original.to_dict().items()}))

    assert restored.to_dict() == original.to_dict()


def test_exchange_config_with_margin_mode_preserves_other_fields():
    original = ExchangeConfig(api_key="k", api_secret="s", http_proxy="http://127.0.0.1:7890")

    routed = original.with_margin_mode(MarginMode.CROSS_MARGIN)

    assert routed.margin_mode == MarginMode.CROSS_MARGIN
    assert routed.api_key == "k"
    assert routed.http_proxy == "http://127.0.0.1:7890"
    assert original.margin_mode == MarginMode.SPOT


def test_parse_exchange_config_rejects_unknown_exchange_name():
    import pytest

    with pytest.raises(ValueError):
        parse_exchange_config("NOT_AN_EXCHANGE")
