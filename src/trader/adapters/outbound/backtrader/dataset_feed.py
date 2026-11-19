"""Backtrader feed builders and loader for resolved datasets (CSV cache and DB klines)."""

from __future__ import annotations

from datetime import datetime

from trader.adapters.outbound.backtrader.csvdata import BinanceCSVData
from trader.adapters.outbound.backtrader.data import BinanceData
from trader.adapters.outbound.files.dataset import CsvDatasetFileStore
from trader.core.marketdata.domain import DatasetPreparationFailure, DatasetPreparationResult, DatasetRef
from trader.core.marketdata.use_cases.check_klines import CoverageReport, inspect_coverage
from trader.core.marketdata.use_cases.dataset import DatasetResolver as _DatasetResolver

__all__ = [
    "BacktraderDatasetFeedLoader",
    "CoverageReport",
    "DatasetPreparationFailure",
    "DatasetPreparationResult",
    "DatasetRef",
    "build_csv_feed",
    "build_db_feed",
]


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


class BacktraderDatasetFeedLoader(_DatasetResolver):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("file_store", CsvDatasetFileStore())
        super().__init__(*args, **kwargs)

    async def inspect_coverage(
        self,
        symbol_interval,
        start_time: int = 0,
        end_time: int = 0,
    ) -> CoverageReport:
        """Inspect coverage with one range query; never issue per-candle lookups."""
        return await inspect_coverage(self.kline_repository, symbol_interval, start_time, end_time)

    async def sync_range(
        self,
        symbol_interval,
        start_time: int,
        end_time: int,
        allow_download: bool = True,
        force_sync: bool = False,
    ):
        """Canonical range-sync seam: refresh one kline range and return its dataset ref."""
        return await self.prepare(
            symbol_interval,
            start_time,
            end_time,
            allow_download=allow_download,
            force_sync=force_sync,
        )

    @staticmethod
    def build_csv_feed(
        data_path,
        *,
        data_start_time: int | None = None,
        end_time: int | None = None,
        use_range: bool = False,
    ):
        """Build a backtrader CSV feed for a resolved dataset path."""
        return build_csv_feed(
            data_path,
            data_start_time=data_start_time,
            end_time=end_time,
            use_range=use_range,
        )

    async def load_backtest_feed(
        self,
        dataset_ref: DatasetRef,
        *,
        data_path=None,
        data_start_time: int | None = None,
        use_data_range: bool = False,
    ):
        """Build a backtrader feed for a resolved dataset (CSV cache or DB)."""
        if dataset_ref.source_type == "csv" or data_path is not None or dataset_ref.path is not None:
            return build_csv_feed(
                data_path or dataset_ref.path,
                data_start_time=data_start_time if data_start_time is not None else dataset_ref.start_time,
                end_time=dataset_ref.end_time,
                use_range=use_data_range,
            )

        from trader.core.shared.domain import Interval, SymbolInterval

        collection_name = SymbolInterval(dataset_ref.symbol, Interval(dataset_ref.interval)).name()
        start_time = data_start_time if data_start_time is not None else dataset_ref.start_time
        klines = list(await self.kline_repository.get_klines(collection_name, start_time, dataset_ref.end_time) or [])
        if not klines:
            raise ValueError(f"no kline data available for dataset={dataset_ref.dataset_key}")
        return build_db_feed(klines)
