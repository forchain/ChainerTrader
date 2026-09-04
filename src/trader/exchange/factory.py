from __future__ import annotations

from trader.exchange.binance_native_driver import BinanceNativeExchangeDriver
from trader.exchange.ccxt_driver import CcxtExchangeDriver
from trader.exchange.driver import ExchangeDriver, ExchangeDriverType
from trader.exchange.exchange_config import ExchangeConfig


def build_exchange_driver(cfg: ExchangeConfig) -> ExchangeDriver:
    driver = cfg.driver if hasattr(cfg, "driver") else ExchangeDriverType.CCXT
    if driver == ExchangeDriverType.CCXT:
        return CcxtExchangeDriver(cfg)
    if driver == ExchangeDriverType.BINANCE_NATIVE:
        return BinanceNativeExchangeDriver(cfg)
    raise ValueError(f"unsupported exchange driver: {driver}")
