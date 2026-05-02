from __future__ import annotations

from dataclasses import dataclass
from logging import Logger

from trader.database.models import AvailabilityModel


@dataclass(frozen=True)
class AvailabilityState:
    exchange: str
    symbol: str
    interval: str
    earliest_known_open_time: int
    updated_at: int
    source: str


def model_to_availability_state(row: AvailabilityModel) -> AvailabilityState:
    return AvailabilityState(
        exchange=row.exchange,
        symbol=row.symbol,
        interval=row.interval,
        earliest_known_open_time=row.earliest_known_open_time,
        updated_at=row.updated_at,
        source=row.source,
    )


class AvailabilityCol:
    def __init__(self, log: Logger):
        self.log = log

    async def get_state(self, exchange: str, symbol: str, interval: str) -> AvailabilityState | None:
        row = await AvailabilityModel.filter(exchange=exchange, symbol=symbol, interval=interval).first()
        if row is None:
            return None
        return model_to_availability_state(row)

    async def get_earliest_known_open_time(self, exchange: str, symbol: str, interval: str) -> int | None:
        state = await self.get_state(exchange, symbol, interval)
        if state is None:
            return None
        return state.earliest_known_open_time

    async def update_earliest_known_open_time(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        earliest_known_open_time: int,
        source: str = "backward_fill",
    ) -> bool:
        current = await AvailabilityModel.filter(exchange=exchange, symbol=symbol, interval=interval).first()
        if current is not None and current.earliest_known_open_time <= earliest_known_open_time:
            return False

        await AvailabilityModel.update_or_create(
            exchange=exchange,
            symbol=symbol,
            interval=interval,
            defaults={
                "earliest_known_open_time": earliest_known_open_time,
                "updated_at": earliest_known_open_time,
                "source": source,
            },
        )
        return True
