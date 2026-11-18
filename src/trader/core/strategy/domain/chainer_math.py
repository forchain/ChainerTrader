"""Pure ChainerTrader calculations shared by the kernel and the Pine-compatible library."""

from __future__ import annotations

import math
from typing import Optional


def normalize_direction(direction: str) -> str:
    raw = (direction or "").strip()
    upper = raw.upper()
    try:
        num = float(raw)
    except ValueError:
        num = None

    if num is not None:
        return "LONG" if num > 0 else "SHORT"
    return "SHORT" if upper == "SHORT" else "LONG"


def breakeven_price(direction: str, entry_price: float, initial_stop: float, close: float) -> Optional[float]:
    dir_norm = normalize_direction(direction)

    if any(math.isnan(v) for v in (entry_price, initial_stop, close)):
        return None

    if dir_norm == "LONG":
        risk = entry_price - initial_stop
    else:
        risk = initial_stop - entry_price

    if risk <= 0:
        return None

    if dir_norm == "LONG":
        profit = close - entry_price
    else:
        profit = entry_price - close

    n_float = profit / risk
    n = math.floor(n_float + 1e-10)
    if n <= 0:
        return None

    if dir_norm == "LONG":
        return entry_price + (n - 1) * risk
    return entry_price - (n - 1) * risk


def risk_reward_price(direction: str, entry_price: float, stop_price: float, risk_reward_ratio: float) -> Optional[float]:
    dir_norm = normalize_direction(direction)

    if risk_reward_ratio <= 0:
        return None

    if dir_norm == "LONG":
        risk = entry_price - stop_price
        if risk <= 0:
            return None
        return entry_price + risk_reward_ratio * risk

    risk = stop_price - entry_price
    if risk <= 0:
        return None
    return entry_price - risk_reward_ratio * risk


def stop_hit(direction: str, stop_price_val: Optional[float], low: float, high: float) -> bool:
    if stop_price_val is None or math.isnan(stop_price_val):
        return False

    dir_norm = normalize_direction(direction)

    if dir_norm == "LONG":
        return low <= stop_price_val
    return high >= stop_price_val
