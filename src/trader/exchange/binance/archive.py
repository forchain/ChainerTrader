from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Callable
from xml.etree import ElementTree

import requests

from trader.utils.symbol_interval import SymbolInterval

BINANCE_PUBLIC_DATA_S3_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/"


def parse_earliest_daily_archive_open_time(payload: str, symbol: str, interval: str) -> int | None:
    """Return the UTC start of the earliest daily archive date for a symbol interval."""
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return None

    archive_pattern = re.compile(
        rf"^data/spot/daily/klines/{re.escape(symbol)}/{re.escape(interval)}/"
        rf"{re.escape(symbol)}-{re.escape(interval)}-(\d{{4}}-\d{{2}}-\d{{2}})\.zip$"
    )
    dates = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "Key" or not node.text:
            continue
        match = archive_pattern.fullmatch(node.text)
        if match:
            dates.append(match.group(1))
    if not dates:
        return None
    try:
        return int(datetime.strptime(min(dates), "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


def find_earliest_daily_archive_open_time(
    symbol_interval: SymbolInterval,
    *,
    http_get: Callable = requests.get,
) -> int | None:
    """Query Binance Public Data's S3 listing for the earliest daily archive date."""
    symbol = symbol_interval.symbol()
    interval = symbol_interval.interval.value
    prefix = f"data/spot/daily/klines/{symbol}/{interval}/"
    try:
        response = http_get(
            BINANCE_PUBLIC_DATA_S3_URL,
            params={"list-type": "2", "prefix": prefix, "max-keys": 100},
            timeout=15,
        )
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    return parse_earliest_daily_archive_open_time(response.text, symbol, interval)
