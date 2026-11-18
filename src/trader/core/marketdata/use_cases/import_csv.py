"""CSV kline import use case."""

from __future__ import annotations

from trader.core.marketdata.interfaces import KlineRepository
from trader.core.shared.domain import Kline, SymbolInterval, add_time_duration


def parse_csv_kline_rows(rows: list[list[str]]) -> list[Kline]:
    klines: list[Kline] = []
    for row in rows[1:]:
        if len(row) != 12:
            continue
        (
            open_time,
            openp,
            high,
            low,
            close,
            volume,
            close_time,
            quote_volume,
            count,
            taker_buy_volume,
            taker_buy_quote_volume,
            ignore,
        ) = row
        klines.append(
            Kline(
                int(int(open_time) / 1000),
                float(openp),
                float(high),
                float(low),
                float(close),
                int(int(close_time) / 1000),
                float(volume),
                float(quote_volume),
                int(count),
                float(taker_buy_volume),
                float(taker_buy_quote_volume),
                float(ignore),
            )
        )
    return klines


def validate_kline_interval(klines: list[Kline], symbol_interval: SymbolInterval) -> bool:
    if len(klines) < 2:
        return True
    next_open_time = add_time_duration(klines[0].open_time, symbol_interval.interval, 1)
    return next_open_time == klines[1].open_time


async def import_csv_klines(
    kline_repository: KlineRepository,
    name: str,
    klines: list[Kline],
    source: str = "csv",
) -> int:
    return await kline_repository.add_klines(name, klines, source=source)
