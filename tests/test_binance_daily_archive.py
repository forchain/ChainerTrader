from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import requests

from trader.exchange.binance.archive import (
    find_earliest_daily_archive_open_time,
    parse_earliest_daily_archive_open_time,
)
from trader.exchange.binance.exchange import BinanceExchange
from trader.utils.symbol_interval import Interval, SymbolInterval


def test_parse_earliest_daily_archive_open_time_ignores_checksums_and_uses_utc_day_start():
    payload = """<?xml version="1.0" encoding="UTF-8"?>
    <ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
      <Contents><Key>data/spot/daily/klines/ETHUSDT/1d/ETHUSDT-1d-2017-08-17.zip.CHECKSUM</Key></Contents>
      <Contents><Key>data/spot/daily/klines/ETHUSDT/1d/ETHUSDT-1d-2017-08-17.zip</Key></Contents>
      <Contents><Key>data/spot/daily/klines/ETHUSDT/1d/ETHUSDT-1d-2017-08-18.zip</Key></Contents>
      <Contents><Key>data/spot/daily/klines/ETHUSDT/1d/NOT-AN-ARCHIVE.zip</Key></Contents>
    </ListBucketResult>"""

    result = parse_earliest_daily_archive_open_time(payload, "ETHUSDT", "1d")

    assert result == int(datetime(2017, 8, 17, tzinfo=timezone.utc).timestamp())


def test_find_earliest_daily_archive_open_time_returns_none_for_http_or_parse_failure():
    symbol_interval = SymbolInterval("BTC-USDT", Interval.INTERVAL_1d)

    assert find_earliest_daily_archive_open_time(
        symbol_interval,
        http_get=lambda *args, **kwargs: SimpleNamespace(status_code=503, text="unavailable"),
    ) is None
    assert find_earliest_daily_archive_open_time(
        symbol_interval,
        http_get=lambda *args, **kwargs: SimpleNamespace(status_code=200, text="not xml"),
    ) is None
    assert find_earliest_daily_archive_open_time(
        symbol_interval,
        http_get=lambda *args, **kwargs: (_ for _ in ()).throw(requests.ConnectionError("offline")),
    ) is None


def test_parse_earliest_daily_archive_open_time_returns_none_for_an_empty_listing():
    payload = "<ListBucketResult xmlns=\"http://s3.amazonaws.com/doc/2006-03-01/\" />"

    assert parse_earliest_daily_archive_open_time(payload, "BTCUSDT", "1d") is None


def test_binance_exchange_delegates_daily_archive_lookup():
    symbol_interval = SymbolInterval("BTC-USDT", Interval.INTERVAL_1d)
    exchange = object.__new__(BinanceExchange)

    with patch("trader.exchange.binance.exchange.find_earliest_daily_archive_open_time", return_value=1_500_000_000):
        assert exchange.get_earliest_daily_archive_open_time(symbol_interval) == 1_500_000_000
