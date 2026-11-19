"""Domain exceptions for the market-data bounded context."""

from __future__ import annotations


class KlineRangeError(ValueError):
    """Raised when a kline range has start after end."""


class DatasetCoverageError(ValueError):
    """Raised when a requested dataset cannot be covered by available klines."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
