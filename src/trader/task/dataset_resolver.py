"""Compatibility entry point for the marketdata dataset use case.

The behaviour lives in ``trader.core.marketdata.use_cases.dataset``. This module
keeps existing task/tool imports working and injects the CSV file adapter.
"""

from __future__ import annotations

import time
from typing import Awaitable, Callable

from trader.adapters.outbound.files.dataset import CsvDatasetFileStore
from trader.core.marketdata.domain import DatasetPreparationFailure, DatasetPreparationResult, DatasetRef
from trader.core.marketdata.use_cases.dataset import DatasetResolver as _DatasetResolver

RangeDownloader = Callable[..., Awaitable[bool]]

__all__ = [
    "DatasetPreparationFailure",
    "DatasetPreparationResult",
    "DatasetRef",
    "DatasetResolver",
    "RangeDownloader",
    "time",
]


class DatasetResolver(_DatasetResolver):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("file_store", CsvDatasetFileStore())
        super().__init__(*args, **kwargs)
