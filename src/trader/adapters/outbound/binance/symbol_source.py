from __future__ import annotations

from typing import Any, Callable

import requests

from trader.core.optimization.domain import BINANCE_EXCHANGE_INFO_URL, CMC_INDEXES
from trader.core.optimization.exceptions import OptimizationConfigError


def default_fetch_json(url: str) -> dict[str, Any]:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object from {url}")
    return payload


class HttpCandidateSymbolSource:
    """HTTP adapter implementing CandidateSymbolSource for Binance exchange info and CMC index feeds."""

    def __init__(self, fetch_json: Callable[[str], dict[str, Any]] = default_fetch_json):
        self.fetch_json = fetch_json

    def fetch_binance_exchange_info(self) -> dict[str, Any]:
        return self.fetch_json(BINANCE_EXCHANGE_INFO_URL)

    def fetch_cmc_index(self, index: str) -> dict[str, Any]:
        normalized = str(index).upper()
        if normalized not in CMC_INDEXES:
            raise OptimizationConfigError(f"unsupported market index: {index}")
        return self.fetch_json(CMC_INDEXES[normalized]["api_url"])
