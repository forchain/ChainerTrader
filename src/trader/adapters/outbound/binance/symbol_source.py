from __future__ import annotations

from typing import Any, Callable

import requests

from trader.core.optimization.domain import BINANCE_EXCHANGE_INFO_URL, CMC_INDEXES
from trader.core.optimization.exceptions import OptimizationConfigError
from trader.core.shared.paths import get_file_path


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


def get_symbol_top(api_key: str, limit=100):
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"

    params = {"start": 1, "limit": limit, "convert": "USD"}

    headers = {"Accepts": "application/json", "X-CMC_PRO_API_KEY": api_key}

    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        return None

    data = response.json()

    ret = []
    for coin in data["data"]:
        ret.append(coin["symbol"])
    return ret


def write_symbols_top100_config(api_key: str, file_path="symbols_top100.txt", quote="USDT"):
    symbols = get_symbol_top(api_key)
    if symbols is None or len(symbols) <= 0:
        return False
    with open(get_file_path(file_path), "w", encoding="utf-8") as f:
        for sy in symbols:
            if sy == quote:
                continue
            f.write(sy + quote + "\n")
        return True
