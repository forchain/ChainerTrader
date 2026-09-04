from __future__ import annotations

from logging import Logger
from typing import Any

from trader.database.models import KlineModel
from trader.utils.kline import Kline

DEFAULT_EXCHANGE = "BINANCE"


def split_symbol_interval(name: str) -> tuple[str, str]:
    symbol, sep, interval = name.partition("-")
    if not sep or not symbol or not interval:
        raise ValueError(f"invalid symbol interval name: {name}")
    return symbol, interval


def kline_to_model_defaults(kl: Kline, raw_payload: Any | None = None, source: str = "unknown") -> dict[str, Any]:
    return {
        "open": kl.open,
        "high": kl.high,
        "low": kl.low,
        "close": kl.close,
        "close_time": kl.close_time,
        "volume": kl.volume,
        "vol_quote": kl.vol_quote,
        "trades": kl.trades,
        "vol_taker_base": kl.vol_taker_base,
        "vol_taker_quote": kl.vol_taker_quote,
        "ignore": kl.ignore,
        "raw_payload": raw_payload,
        "source": source,
    }


def model_to_kline(row: KlineModel) -> Kline:
    return Kline(
        open_time=row.open_time,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        close_time=row.close_time,
        volume=row.volume,
        vol_quote=row.vol_quote,
        trades=row.trades,
        vol_taker_base=row.vol_taker_base,
        vol_taker_quote=row.vol_taker_quote,
        ignore=row.ignore,
    )


class KlineCol:
    def __init__(self, log: Logger, exchange: str = DEFAULT_EXCHANGE):
        self.log = log
        self.exchange = exchange

    async def get_latest_kline(self, name: str) -> Kline | None:
        symbol, interval = split_symbol_interval(name)
        row = await self._base_query(symbol, interval).order_by("-open_time").first()
        if row is None:
            return None
        kl = model_to_kline(row)
        self.log.debug(f"get latest kline({name}:{row.open_time}):{kl.to_json()}")
        return kl

    async def get_latest_klines(self, name: str, limit: int) -> list[Kline] | None:
        symbol, interval = split_symbol_interval(name)
        rows = await self._base_query(symbol, interval).order_by("-open_time").limit(limit)
        klines = [model_to_kline(row) for row in rows]
        if len(klines) > 1:
            klines.reverse()
        return klines

    async def add_klines(
        self,
        name: str,
        klines: list[Kline],
        raw_payloads: list[Any] | None = None,
        source: str = "unknown",
    ) -> int:
        if len(klines) <= 0:
            return 0

        symbol, interval = split_symbol_interval(name)
        raw_payloads = raw_payloads or [None] * len(klines)
        total = 0
        seen: set[int] = set()
        for kl, raw_payload in zip(klines, raw_payloads, strict=False):
            if kl.open_time in seen:
                continue
            seen.add(kl.open_time)
            _, created = await KlineModel.get_or_create(
                exchange=self.exchange,
                symbol=symbol,
                interval=interval,
                open_time=kl.open_time,
                defaults=kline_to_model_defaults(kl, raw_payload=raw_payload, source=source),
            )
            if created:
                total += 1

        self.log.debug(f"add klines, total:{total}")
        return total

    async def get_first_kline(self, name: str) -> Kline | None:
        symbol, interval = split_symbol_interval(name)
        row = await self._base_query(symbol, interval).order_by("open_time").first()
        if row is None:
            return None
        kl = model_to_kline(row)
        self.log.debug(f"get first kline({name}:{row.open_time}):{kl.to_json()}")
        return kl

    async def get_kline(self, name: str, open_time: int) -> Kline | None:
        symbol, interval = split_symbol_interval(name)
        row = await self._base_query(symbol, interval).filter(open_time=open_time).first()
        if row is None:
            return None
        kl = model_to_kline(row)
        self.log.debug(f"get kline({name}:{row.open_time}):{kl.to_json()}")
        return kl

    async def get_all_klines(self, name: str) -> list[Kline] | None:
        symbol, interval = split_symbol_interval(name)
        rows = await self._base_query(symbol, interval).order_by("open_time")
        return [model_to_kline(row) for row in rows]

    async def get_klines(self, name: str, start_time: int = 0, end_time: int = 0) -> list[Kline] | None:
        if start_time == 0 and end_time == 0:
            return await self.get_all_klines(name)
        if start_time > end_time and end_time > 0:
            return await self.get_all_klines(name)

        symbol, interval = split_symbol_interval(name)
        query = self._base_query(symbol, interval)
        if start_time != 0:
            query = query.filter(open_time__gte=start_time)
        if end_time != 0:
            query = query.filter(open_time__lte=end_time)
        rows = await query.order_by("open_time")
        return [model_to_kline(row) for row in rows]

    async def delete_klines_in_range(self, name: str, start_time: int, end_time: int) -> int:
        symbol, interval = split_symbol_interval(name)
        deleted_count = await self._base_query(symbol, interval).filter(open_time__gte=start_time, open_time__lte=end_time).delete()
        self.log.info(f"delete klines in range [{start_time}, {end_time}], deleted: {deleted_count}")
        return deleted_count

    def _base_query(self, symbol: str, interval: str):
        return KlineModel.filter(exchange=self.exchange, symbol=symbol, interval=interval)
