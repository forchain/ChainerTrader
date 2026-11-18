"""Realtime kline update values and warmup/backfill planning rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from trader.core.shared.domain import Interval, Kline, get_time_duration

DEFAULT_BACKFILL_LIMIT = 500


class BackfillRequestKind(Enum):
    NONE = "none"
    LATEST = "latest"
    RANGE = "range"


class KlineUpdateError(ValueError):
    pass


@dataclass(frozen=True)
class BackfillPlan:
    kind: BackfillRequestKind
    limit: int
    missing_count: int
    start_time: int | None = None
    end_time: int | None = None
    truncated: bool = False
    diagnostic: str = ""


@dataclass(frozen=True)
class KlineUpdate:
    exchange: str
    symbol: str
    interval: str
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    event_time: int
    is_closed: bool
    vol_quote: float = 0.0
    trades: int = 0
    vol_taker_base: float = 0.0
    vol_taker_quote: float = 0.0
    ignore: float = 0.0

    def key(self) -> tuple[str, str, str, int]:
        return (self.exchange, self.symbol, self.interval, self.open_time)

    def to_kline(self) -> Kline:
        return Kline(
            self.open_time,
            self.open,
            self.high,
            self.low,
            self.close,
            self.close_time,
            self.volume,
            self.vol_quote,
            self.trades,
            self.vol_taker_base,
            self.vol_taker_quote,
            self.ignore,
        )

    def to_chart_candle(self) -> dict[str, float | int | bool]:
        return {
            "time": self.open_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "closed": self.is_closed,
        }


class KlineUpdateBuffer:
    def __init__(self):
        self._closed_open_times: set[tuple[str, str, str, int]] = set()

    def accept(self, update: KlineUpdate) -> bool:
        key = update.key()
        if key in self._closed_open_times:
            return False

        stale_closed_times = [
            closed_key
            for closed_key in self._closed_open_times
            if closed_key[:3] == key[:3] and closed_key[3] > update.open_time
        ]
        if stale_closed_times:
            return False

        if update.is_closed:
            self._closed_open_times.add(key)
        return True


def latest_closed_open_time(now: int, interval: Interval) -> int:
    duration = get_time_duration(interval)
    current_open = (int(now) // duration) * duration
    return current_open - duration


def plan_initial_backfill(
    latest_kline: Kline | None,
    *,
    now: int,
    interval: Interval,
    limit: int = DEFAULT_BACKFILL_LIMIT,
) -> BackfillPlan:
    cap = max(1, int(limit))
    if latest_kline is None:
        return BackfillPlan(kind=BackfillRequestKind.LATEST, limit=cap, missing_count=cap)

    duration = get_time_duration(interval)
    last_closed_open = latest_closed_open_time(now, interval)
    missing_count = max(0, int((last_closed_open - int(latest_kline.open_time)) / duration))

    if missing_count <= 0:
        return BackfillPlan(kind=BackfillRequestKind.NONE, limit=0, missing_count=0)

    if missing_count > cap:
        return BackfillPlan(
            kind=BackfillRequestKind.LATEST,
            limit=cap,
            missing_count=missing_count,
            truncated=True,
            diagnostic=f"missing {missing_count} closed candles; startup backfill truncated to latest {cap}",
        )

    start_time = int(latest_kline.open_time) + duration
    end_time = start_time + (missing_count - 1) * duration
    return BackfillPlan(
        kind=BackfillRequestKind.RANGE,
        limit=missing_count,
        missing_count=missing_count,
        start_time=start_time,
        end_time=end_time,
    )
