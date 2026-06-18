from __future__ import annotations

import time
from dataclasses import dataclass
from logging import Logger

from tortoise.exceptions import OperationalError

from trader.database.models import AvailabilityModel


@dataclass(frozen=True)
class AvailabilityState:
    exchange: str
    symbol: str
    interval: str
    earliest_known_open_time: int | None
    cached_start_open_time: int | None
    cached_end_open_time: int | None
    updated_at: int
    source: str


def model_to_availability_state(row: AvailabilityModel) -> AvailabilityState:
    return AvailabilityState(
        exchange=row.exchange,
        symbol=row.symbol,
        interval=row.interval,
        earliest_known_open_time=row.earliest_known_open_time,
        cached_start_open_time=getattr(row, "cached_start_open_time", None),
        cached_end_open_time=getattr(row, "cached_end_open_time", None),
        updated_at=row.updated_at,
        source=row.source,
    )


class AvailabilityCol:
    def __init__(self, log: Logger):
        self.log = log

    async def get_state(self, exchange: str, symbol: str, interval: str) -> AvailabilityState | None:
        try:
            row = await AvailabilityModel.filter(exchange=exchange, symbol=symbol, interval=interval).first()
        except OperationalError as exc:
            self.log.warning(f"availability state unavailable; database migration may be pending: {exc}")
            return None
        if row is None:
            return None
        return model_to_availability_state(row)

    async def get_earliest_known_open_time(self, exchange: str, symbol: str, interval: str) -> int | None:
        try:
            row = await AvailabilityModel.filter(exchange=exchange, symbol=symbol, interval=interval).only(
                "earliest_known_open_time"
            ).first()
        except OperationalError as exc:
            self.log.warning(f"availability earliest boundary unavailable; database migration may be pending: {exc}")
            return None
        if row is None:
            return None
        return row.earliest_known_open_time

    async def get_cached_open_time_range(self, exchange: str, symbol: str, interval: str) -> tuple[int, int] | None:
        if not self._model_supports_cached_open_time_range():
            self.log.warning("availability cached range fields are unavailable; run database migrations to enable cached coverage")
            return None
        state = await self.get_state(exchange, symbol, interval)
        if state is None or state.cached_start_open_time is None or state.cached_end_open_time is None:
            return None
        if state.cached_start_open_time > state.cached_end_open_time:
            return None
        return state.cached_start_open_time, state.cached_end_open_time

    async def update_earliest_known_open_time(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        earliest_known_open_time: int,
        source: str = "backward_fill",
    ) -> bool:
        current = await AvailabilityModel.filter(exchange=exchange, symbol=symbol, interval=interval).first()
        if (
            current is not None
            and current.earliest_known_open_time is not None
            and current.earliest_known_open_time <= earliest_known_open_time
        ):
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

    async def update_cached_open_time_range(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        cached_start_open_time: int,
        cached_end_open_time: int,
        source: str = "dataset_resolver",
    ) -> bool:
        if cached_start_open_time > cached_end_open_time:
            return False
        if not self._model_supports_cached_open_time_range():
            self.log.warning("availability cached range fields are unavailable; run database migrations to enable cached coverage")
            return False

        try:
            current = await AvailabilityModel.filter(exchange=exchange, symbol=symbol, interval=interval).first()
        except OperationalError as exc:
            self.log.warning(f"availability cached range unavailable; database migration may be pending: {exc}")
            return False
        if current is None:
            try:
                await AvailabilityModel.create(
                    exchange=exchange,
                    symbol=symbol,
                    interval=interval,
                    earliest_known_open_time=None,
                    cached_start_open_time=cached_start_open_time,
                    cached_end_open_time=cached_end_open_time,
                    updated_at=int(time.time()),
                    source=source,
                )
            except OperationalError as exc:
                self.log.warning(f"availability cached range not persisted; database migration may be pending: {exc}")
                return False
            return True

        next_start = (
            cached_start_open_time
            if current.cached_start_open_time is None
            else min(current.cached_start_open_time, cached_start_open_time)
        )
        next_end = (
            cached_end_open_time
            if current.cached_end_open_time is None
            else max(current.cached_end_open_time, cached_end_open_time)
        )
        if next_start == current.cached_start_open_time and next_end == current.cached_end_open_time:
            return False

        current.cached_start_open_time = next_start
        current.cached_end_open_time = next_end
        current.updated_at = int(time.time())
        current.source = source
        try:
            await current.save()
        except OperationalError as exc:
            self.log.warning(f"availability cached range not persisted; database migration may be pending: {exc}")
            return False
        return True

    def _model_supports_cached_open_time_range(self) -> bool:
        fields_map = getattr(getattr(AvailabilityModel, "_meta", None), "fields_map", {})
        return "cached_start_open_time" in fields_map and "cached_end_open_time" in fields_map
