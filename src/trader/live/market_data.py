from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from trader.utils.kline import Kline
from trader.utils.symbol_interval import Interval, get_time_duration

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


def normalize_binance_kline_message(message: Any, exchange: str = "BINANCE") -> KlineUpdate:
    payload = _to_mapping(message)
    if "k" not in payload:
        raise KlineUpdateError("missing kline payload field 'k'")

    event_time_ms = _required(payload, "E", "event time")
    kline = _to_mapping(payload["k"])
    closed = _required(kline, "x", "closed flag")
    if not isinstance(closed, bool):
        raise KlineUpdateError("closed flag 'x' must be a boolean")

    return KlineUpdate(
        exchange=str(exchange),
        symbol=str(_required(kline, "s", "symbol") or _required(payload, "s", "symbol")),
        interval=str(_required(kline, "i", "interval")),
        open_time=_ms_to_seconds(_required(kline, "t", "open time")),
        close_time=_ms_to_seconds(_required(kline, "T", "close time")),
        open=float(_required(kline, "o", "open")),
        close=float(_required(kline, "c", "close")),
        high=float(_required(kline, "h", "high")),
        low=float(_required(kline, "l", "low")),
        volume=float(_required(kline, "v", "volume")),
        event_time=_ms_to_seconds(event_time_ms),
        is_closed=closed,
        vol_quote=float(kline.get("q", 0.0) or 0.0),
        trades=int(kline.get("n", 0) or 0),
        vol_taker_base=float(kline.get("V", 0.0) or 0.0),
        vol_taker_quote=float(kline.get("Q", 0.0) or 0.0),
        ignore=float(kline.get("B", 0.0) or 0.0),
    )


def _to_mapping(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True)
    if hasattr(value, "dict"):
        return value.dict()
    raise KlineUpdateError(f"unsupported Binance kline message type: {type(value).__name__}")


def _required(payload: dict, key: str, label: str) -> Any:
    if key not in payload or payload[key] is None:
        raise KlineUpdateError(f"missing {label} field '{key}'")
    return payload[key]


def _ms_to_seconds(value: Any) -> int:
    return int(int(value) / 1000)
