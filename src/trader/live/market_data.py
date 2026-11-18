"""Compatibility entry point for realtime kline values and Binance normalization.

Warmup/backfill rules live in ``trader.core.marketdata.warmup``; the Binance
message normalizer lives in the market-stream adapter.
"""

from __future__ import annotations

from trader.adapters.outbound.marketstream.binance import normalize_binance_kline_message
from trader.core.marketdata.warmup import (
    DEFAULT_BACKFILL_LIMIT,
    BackfillPlan,
    BackfillRequestKind,
    KlineUpdate,
    KlineUpdateBuffer,
    KlineUpdateError,
    latest_closed_open_time,
    plan_initial_backfill,
)

__all__ = [
    "DEFAULT_BACKFILL_LIMIT",
    "BackfillPlan",
    "BackfillRequestKind",
    "KlineUpdate",
    "KlineUpdateBuffer",
    "KlineUpdateError",
    "latest_closed_open_time",
    "normalize_binance_kline_message",
    "plan_initial_backfill",
]
