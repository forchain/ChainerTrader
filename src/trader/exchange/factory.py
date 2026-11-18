from __future__ import annotations

from trader.adapters.outbound.binance.ccxt_driver import CcxtExchangeDriver
from trader.adapters.outbound.binance.native_driver import BinanceNativeExchangeDriver
from trader.core.exchange.interfaces import ExchangeClient
from trader.exchange.driver import ExchangeDriverType
from trader.exchange.exchange_config import ExchangeConfig


def build_exchange_driver(cfg: ExchangeConfig) -> ExchangeClient:
    driver = cfg.driver if hasattr(cfg, "driver") else ExchangeDriverType.CCXT
    if driver == ExchangeDriverType.CCXT:
        return CcxtExchangeDriver(cfg)
    if driver == ExchangeDriverType.BINANCE_NATIVE:
        return BinanceNativeExchangeDriver(cfg)
    raise ValueError(f"unsupported exchange driver: {driver}")
