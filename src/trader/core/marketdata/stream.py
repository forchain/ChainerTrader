"""Market stream domain types shared by the hub and its connector port."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class MarketStreamKey:
    exchange: str
    symbol: str
    interval: str

    def stream_name(self) -> str:
        return f"{self.symbol.lower()}@kline_{self.interval}"


class MarketStreamState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass(frozen=True)
class MarketStreamStatus:
    key: MarketStreamKey
    state: MarketStreamState
    subscriber_count: int
    last_error: str | None = None
