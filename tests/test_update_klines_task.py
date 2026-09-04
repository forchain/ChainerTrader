import asyncio
import sys
from datetime import datetime, timedelta
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _ensure_pymongo_stub():
    if "pymongo" in sys.modules:
        return

    pymongo_module = ModuleType("pymongo")
    pymongo_module.MongoClient = object
    pymongo_module.ASCENDING = 1
    pymongo_module.DESCENDING = -1
    sys.modules["pymongo"] = pymongo_module

    pymongo_synchronous = ModuleType("pymongo.synchronous")
    sys.modules["pymongo.synchronous"] = pymongo_synchronous

    collection_module = ModuleType("pymongo.synchronous.collection")
    collection_module.Collection = object
    sys.modules["pymongo.synchronous.collection"] = collection_module


_ensure_pymongo_stub()

def _ensure_binance_exchange_stub():
    module_name = "trader.exchange.binance.exchange"
    if module_name in sys.modules:
        return

    binance_module = ModuleType(module_name)

    class _BinanceExchange:  # pragma: no cover - stub only
        pass

    binance_module.BinanceExchange = _BinanceExchange
    sys.modules[module_name] = binance_module


_ensure_binance_exchange_stub()

from trader.task.update_klines_task import download  # noqa: E402
from trader.utils.symbol_interval import Interval, SymbolInterval  # noqa: E402


class DummyLog:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


@pytest.mark.asyncio
async def test_download_uses_collection_name_string():
    log = DummyLog()
    symbol_interval = SymbolInterval("BTC-USDT", Interval.INTERVAL_1h)
    collection_name = "klines-BTCUSDT-1h"
    start_time = int((datetime.now() - timedelta(hours=1)).timestamp())
    quit_event = asyncio.Event()

    latest_record = SimpleNamespace(open_time=int(datetime.now().timestamp()))
    kline_mock = SimpleNamespace(
        get_latest_kline=MagicMock(side_effect=[None, latest_record]),
        add_klines=MagicMock(return_value=1),
    )
    db_manager = SimpleNamespace(kline=kline_mock)

    klines_payload = [object()]
    exchange = SimpleNamespace(
        get_klines_by_start=MagicMock(return_value=klines_payload),
    )

    result = await download(
        "update-task",
        log,
        db_manager,
        collection_name,
        exchange,
        symbol_interval,
        start_time,
        quit_event,
    )

    assert result is True
    first_call_args = kline_mock.get_latest_kline.call_args_list[0].args
    assert first_call_args[0] == collection_name
    add_call_args = kline_mock.add_klines.call_args.args
    assert add_call_args[0] == collection_name
    assert add_call_args[1] is klines_payload

