import asyncio
import sys
from datetime import datetime, timedelta
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

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

    class _BinanceExchange:
        pass

    def get_oldest_time():
        return datetime.strptime("2000-01-01 00:00:00", "%Y-%m-%d %H:%M:%S")

    binance_module.BinanceExchange = _BinanceExchange
    binance_module.get_oldest_time = get_oldest_time
    sys.modules[module_name] = binance_module


_ensure_binance_exchange_stub()

from trader.task.update_klines_task import download_range  # noqa: E402
from trader.utils.symbol_interval import Interval, SymbolInterval, add_time_duration  # noqa: E402


class DummyLog:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


def create_kline_mock(open_time: int):
    return SimpleNamespace(open_time=open_time)


def test_download_range_basic():
    """Test basic download_range functionality."""

    async def _test():
        log = DummyLog()
        symbol_interval = SymbolInterval("BTC-USDT", Interval.INTERVAL_1h)
        collection_name = "klines-BTCUSDT-1h"
        now = int(datetime.now().timestamp())
        start_time = now - 3600
        end_time = now
        quit_event = asyncio.Event()

        # Create kline with open_time equal to end_time, so loop will exit after first batch
        kline1 = create_kline_mock(end_time)
        klines_payload = [kline1]

        kline_mock = SimpleNamespace(
            add_klines=MagicMock(return_value=1),
        )
        db_manager = SimpleNamespace(kline=kline_mock)

        exchange = SimpleNamespace(
            get_klines=MagicMock(return_value=klines_payload),
        )

        result = await download_range(
            "update-task",
            log,
            db_manager,
            collection_name,
            exchange,
            symbol_interval,
            start_time,
            end_time,
            quit_event,
        )

        assert result is True
        add_call_args = kline_mock.add_klines.call_args.args
        assert add_call_args[0] == collection_name
        assert add_call_args[1] is klines_payload

    asyncio.run(_test())


def test_download_range_invalid_range():
    """Test download_range with start > end returns False."""

    async def _test():
        log = DummyLog()
        symbol_interval = SymbolInterval("BTC-USDT", Interval.INTERVAL_1h)
        collection_name = "klines-BTCUSDT-1h"
        now = int(datetime.now().timestamp())
        start_time = now
        end_time = now - 3600
        quit_event = asyncio.Event()

        kline_mock = SimpleNamespace(add_klines=MagicMock())
        db_manager = SimpleNamespace(kline=kline_mock)
        exchange = SimpleNamespace(get_klines=MagicMock())

        result = await download_range(
            "update-task",
            log,
            db_manager,
            collection_name,
            exchange,
            symbol_interval,
            start_time,
            end_time,
            quit_event,
        )

        assert result is False
        exchange.get_klines.assert_not_called()

    asyncio.run(_test())


def test_download_range_quit_event():
    """Test download_range exits when quit event is set."""

    async def _test():
        log = DummyLog()
        symbol_interval = SymbolInterval("BTC-USDT", Interval.INTERVAL_1h)
        collection_name = "klines-BTCUSDT-1h"
        now = int(datetime.now().timestamp())
        start_time = now - 3600
        end_time = now
        quit_event = asyncio.Event()
        quit_event.set()

        kline_mock = SimpleNamespace(add_klines=MagicMock())
        db_manager = SimpleNamespace(kline=kline_mock)
        exchange = SimpleNamespace(get_klines=MagicMock())

        result = await download_range(
            "update-task",
            log,
            db_manager,
            collection_name,
            exchange,
            symbol_interval,
            start_time,
            end_time,
            quit_event,
        )

        assert result is False

    asyncio.run(_test())


def test_download_range_empty_response_retry():
    """Test download_range retries on empty response."""

    async def _test():
        log = DummyLog()
        symbol_interval = SymbolInterval("BTC-USDT", Interval.INTERVAL_1h)
        collection_name = "klines-BTCUSDT-1h"
        now = int(datetime.now().timestamp())
        start_time = now - 3600
        end_time = now
        quit_event = asyncio.Event()

        kline_mock = SimpleNamespace(add_klines=MagicMock())
        db_manager = SimpleNamespace(kline=kline_mock)

        # Return empty 6 times (exceeds max retry of 5)
        exchange = SimpleNamespace(
            get_klines=MagicMock(return_value=[]),
        )

        with patch("trader.task.update_klines_task.DOWNLOAD_SPACE_TIME", 0):
            result = await download_range(
                "update-task",
                log,
                db_manager,
                collection_name,
                exchange,
                symbol_interval,
                start_time,
                end_time,
                quit_event,
            )

        assert result is False
        assert exchange.get_klines.call_count == 6  # 1 initial + 5 retries

    asyncio.run(_test())


class TestTimeRangeScenarios:
    """Test various time range scenarios for _handle_normal_update logic."""

    def setup_method(self):
        self.interval = Interval.INTERVAL_1h
        self.interval_seconds = 3600
        self.now = int(datetime.now().timestamp())

    def test_scenario_no_overlap_end_before_db(self):
        """Case 1: end < db_first - should download [start, end]."""
        db_first = self.now
        db_last = self.now + self.interval_seconds * 10
        start_time = self.now - self.interval_seconds * 10
        end_time = self.now - self.interval_seconds * 5

        assert end_time < db_first

    def test_scenario_start_before_db_end_in_db(self):
        """Case 2: start < db_first <= end <= db_last - should download [start, db_first)."""
        db_first = self.now
        db_last = self.now + self.interval_seconds * 10
        start_time = self.now - self.interval_seconds * 5
        end_time = self.now + self.interval_seconds * 5

        assert start_time < db_first <= end_time <= db_last

    def test_scenario_fully_within_db(self):
        """Case 3: db_first <= start <= end <= db_last - should skip."""
        db_first = self.now
        db_last = self.now + self.interval_seconds * 10
        start_time = self.now + self.interval_seconds * 2
        end_time = self.now + self.interval_seconds * 8

        assert db_first <= start_time and end_time <= db_last

    def test_scenario_start_in_db_end_after(self):
        """Case 4: start >= db_first and db_last < end - should download (db_last, end]."""
        db_first = self.now
        db_last = self.now + self.interval_seconds * 10
        start_time = self.now + self.interval_seconds * 2
        end_time = self.now + self.interval_seconds * 15

        assert start_time >= db_first and db_last < end_time

    def test_scenario_both_outside_db(self):
        """Case 5: start < db_first and db_last < end - should download two segments."""
        db_first = self.now
        db_last = self.now + self.interval_seconds * 10
        start_time = self.now - self.interval_seconds * 5
        end_time = self.now + self.interval_seconds * 15

        assert start_time < db_first and db_last < end_time


class TestDeleteKlinesInRange:
    """Test delete_klines_in_range method."""

    def test_delete_range_called_on_force_update(self):
        """Verify delete is called when force_update is True."""
        from trader.database.kline import KlineCol

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.delete_many.return_value = SimpleNamespace(deleted_count=10)
        mock_db.list_collection_names.return_value = ["klines-BTCUSDT-1h"]
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        log = DummyLog()
        kline_col = KlineCol(mock_db, log)

        result = kline_col.delete_klines_in_range("BTCUSDT-1h", 1000, 2000)

        assert result == 10
        mock_collection.delete_many.assert_called_once()


class TestTaskConfigForceUpdate:
    """Test TaskConfig force_update parameter."""

    def test_force_update_default_false(self):
        """Verify force_update defaults to False."""
        from trader.task.task_config import TaskConfig
        from trader.task.task_type import TaskType

        tc = TaskConfig(1, TaskType.UPDATE_KLINES)
        assert tc.force_update is False

    def test_force_update_set_true(self):
        """Verify force_update can be set to True."""
        from trader.task.task_config import TaskConfig
        from trader.task.task_type import TaskType

        tc = TaskConfig(1, TaskType.UPDATE_KLINES, force_update=True)
        assert tc.force_update is True

    def test_force_update_in_to_dict(self):
        """Verify force_update is included in to_dict output."""
        from trader.task.task_config import TaskConfig
        from trader.task.task_type import TaskType

        tc = TaskConfig(1, TaskType.UPDATE_KLINES, force_update=True)
        d = tc.to_dict()
        assert "force_update" in d
        assert d["force_update"] is True

    def test_parse_task_config_with_force_update(self):
        """Verify force_update is parsed from config."""
        import json

        from trader.task.task_config import parse_task_config

        config = json.dumps(
            [
                {
                    "task_type": "UPDATE_KLINES",
                    "symbol": "BTC-USDT",
                    "interval": "1h",
                    "force_update": True,
                }
            ]
        )

        tasks = parse_task_config(config)
        assert len(tasks) == 1
        assert tasks[0].force_update is True

    def test_parse_task_config_without_force_update(self):
        """Verify force_update defaults to False when not specified."""
        import json

        from trader.task.task_config import parse_task_config

        config = json.dumps(
            [
                {
                    "task_type": "UPDATE_KLINES",
                    "symbol": "BTC-USDT",
                    "interval": "1h",
                }
            ]
        )

        tasks = parse_task_config(config)
        assert len(tasks) == 1
        assert tasks[0].force_update is False
