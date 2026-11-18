from __future__ import annotations

from trader.adapters.outbound.binance.exchange import BinanceExchange
from trader.common.logger import default
from trader.exchange.driver import ExchangeDriverType
from trader.exchange.exchange_config import ExchangeConfig


class BinanceNativeExchangeDriver(BinanceExchange):
    def __init__(self, cfg: ExchangeConfig, log=default(), *, client=None):
        if cfg.driver != ExchangeDriverType.BINANCE_NATIVE:
            cfg = cfg.model_copy(update={"driver": ExchangeDriverType.BINANCE_NATIVE})
        super().__init__(cfg, log, client=client)
