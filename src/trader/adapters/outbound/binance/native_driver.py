from __future__ import annotations

from trader.adapters.outbound.binance.exchange import BinanceExchange
from trader.adapters.outbound.logging.logger import default
from trader.core.exchange.domain import ExchangeConfig, ExchangeDriverType


class BinanceNativeExchangeDriver(BinanceExchange):
    def __init__(self, cfg: ExchangeConfig, log=default(), *, client=None):
        if cfg.driver != ExchangeDriverType.BINANCE_NATIVE:
            cfg = cfg.model_copy(update={"driver": ExchangeDriverType.BINANCE_NATIVE})
        super().__init__(cfg, log, client=client)
