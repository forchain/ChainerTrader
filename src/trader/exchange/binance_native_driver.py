from __future__ import annotations

from trader.exchange.exchange_config import ExchangeConfig


class BinanceNativeExchangeDriver:
    def __init__(self, cfg: ExchangeConfig):
        self.cfg = cfg

    def driver_name(self) -> str:
        return "binance_native"
