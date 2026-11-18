"""Outbound market-stream adapters: Binance websocket and CCXT polling hub."""

from __future__ import annotations

from trader.adapters.outbound.marketstream.binance import (
    BINANCE_SPOT_WS_STREAM_URL,
    BinanceKlineWebSocketAdapter,
    normalize_binance_kline_message,
    run_binance_kline_websocket_smoke,
)
from trader.adapters.outbound.marketstream.ccxt import CcxtPollingMarketStreamAdapter
from trader.adapters.outbound.marketstream.hub import (
    CatchUpCallback,
    MarketStreamConnector,
    MarketStreamHub,
    MarketStreamSubscription,
    ReconnectCallback,
)

GLOBAL_MARKET_STREAM_HUB = MarketStreamHub(CcxtPollingMarketStreamAdapter())

__all__ = [
    "BINANCE_SPOT_WS_STREAM_URL",
    "BinanceKlineWebSocketAdapter",
    "CatchUpCallback",
    "CcxtPollingMarketStreamAdapter",
    "GLOBAL_MARKET_STREAM_HUB",
    "MarketStreamConnector",
    "MarketStreamHub",
    "MarketStreamSubscription",
    "ReconnectCallback",
    "normalize_binance_kline_message",
    "run_binance_kline_websocket_smoke",
]
