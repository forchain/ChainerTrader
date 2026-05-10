from trader.exchange import build_exchange_driver
from trader.exchange.driver import ExchangeDriverType
from trader.exchange.exchange_config import ExchangeConfig
from trader.exchange.exchange_type import ExchangeType


def test_exchange_factory_builds_ccxt_driver():
    driver = build_exchange_driver(ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.CCXT))
    assert driver.driver_name() == "ccxt"


def test_exchange_factory_builds_native_binance_driver():
    driver = build_exchange_driver(
        ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.BINANCE_NATIVE)
    )
    assert driver.driver_name() == "binance_native"
