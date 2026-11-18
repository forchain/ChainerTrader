"""Compatibility entry point for the market stream hub and connectors.

The implementation lives in ``trader.adapters.outbound.marketstream``.
"""

from __future__ import annotations

from trader.adapters.outbound.marketstream import GLOBAL_MARKET_STREAM_HUB
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
from trader.core.marketdata.interfaces import DisconnectCallback, UpdateCallback
from trader.core.marketdata.stream import MarketStreamKey, MarketStreamState, MarketStreamStatus

__all__ = [
    "BINANCE_SPOT_WS_STREAM_URL",
    "BinanceKlineWebSocketAdapter",
    "CatchUpCallback",
    "CcxtPollingMarketStreamAdapter",
    "DisconnectCallback",
    "GLOBAL_MARKET_STREAM_HUB",
    "MarketStreamConnector",
    "MarketStreamHub",
    "MarketStreamKey",
    "MarketStreamState",
    "MarketStreamStatus",
    "MarketStreamSubscription",
    "ReconnectCallback",
    "UpdateCallback",
    "normalize_binance_kline_message",
    "run_binance_kline_websocket_smoke",
]
