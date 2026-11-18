"""Backtrader feed builders for resolved datasets (CSV cache and DB klines)."""

from __future__ import annotations

from datetime import datetime

from trader.adapters.outbound.backtrader.csvdata import BinanceCSVData
from trader.adapters.outbound.backtrader.data import BinanceData


def build_csv_feed(
    data_path,
    *,
    data_start_time: int | None = None,
    end_time: int | None = None,
    use_range: bool = False,
):
    """Build a CSV feed, optionally restricted to the requested time range."""
    if not use_range:
        return BinanceCSVData(dataname=data_path)

    start_time = data_start_time or 0
    stop_time = end_time or 0
    if start_time <= 0 and stop_time <= 0:
        return BinanceCSVData(dataname=data_path)
    if start_time <= 0:
        return BinanceCSVData(
            dataname=data_path,
            todate=datetime.fromtimestamp(stop_time),
        )
    if stop_time <= 0:
        return BinanceCSVData(
            dataname=data_path,
            fromdate=datetime.fromtimestamp(start_time),
        )
    return BinanceCSVData(
        dataname=data_path,
        fromdate=datetime.fromtimestamp(start_time),
        todate=datetime.fromtimestamp(stop_time),
    )


def build_db_feed(klines):
    """Build an in-memory feed from stored klines."""
    return BinanceData(klines)
