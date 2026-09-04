import asyncio
from datetime import datetime
from types import SimpleNamespace

from tortoise import Tortoise

from trader.database.availability import AvailabilityCol, model_to_availability_state
from trader.database.config import build_tortoise_config
from trader.database.kline import KlineCol
from trader.database.task import TaskCol
from trader.utils.kline import Kline
from trader.utils.task_state import TaskState, TaskStateType


class _Log:
    def debug(self, *_args, **_kwargs):
        pass

    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


async def _with_db(fn):
    await Tortoise.init(config=build_tortoise_config("sqlite://:memory:"))
    await Tortoise.generate_schemas()
    try:
        await fn()
    finally:
        await Tortoise.close_connections()


def _kline(open_time: int, close: float = 100.0) -> Kline:
    return Kline(
        open_time=open_time,
        open=close - 1,
        high=close + 2,
        low=close - 2,
        close=close,
        close_time=open_time + 3599,
        volume=10.0,
        vol_quote=1000.0,
        trades=12,
        vol_taker_base=5.0,
        vol_taker_quote=500.0,
        ignore=0.0,
    )


def test_kline_repository_enforces_uniqueness_and_orders_ranges():
    async def run():
        store = KlineCol(_Log())
        inserted = await store.add_klines(
            "BTCUSDT-1h",
            [_kline(3600, 102.0), _kline(0, 100.0), _kline(7200, 104.0), _kline(3600, 102.0)],
            raw_payloads=[{"raw": 1}, {"raw": 2}, {"raw": 3}, {"raw": 4}],
            source="test",
        )

        assert inserted == 3
        assert (await store.add_klines("BTCUSDT-1h", [_kline(3600, 102.0)])) == 0
        assert (await store.get_first_kline("BTCUSDT-1h")).open_time == 0
        assert (await store.get_latest_kline("BTCUSDT-1h")).open_time == 7200
        assert [kl.open_time for kl in await store.get_klines("BTCUSDT-1h", 1, 7200)] == [3600, 7200]
        assert [kl.open_time for kl in await store.get_latest_klines("BTCUSDT-1h", 2)] == [3600, 7200]
        assert await store.delete_klines_in_range("BTCUSDT-1h", 3600, 3600) == 1
        assert [kl.open_time for kl in await store.get_all_klines("BTCUSDT-1h")] == [0, 7200]

    asyncio.run(_with_db(run))


def test_task_repository_upserts_and_reads_task_state():
    async def run():
        store = TaskCol(_Log())
        first = TaskState(7, "first", datetime(2026, 1, 1), commission=0.001, initial_cash=1000)
        first.state = TaskStateType.RUNNING
        second = TaskState(7, "second", datetime(2026, 1, 2), commission=0.002, initial_cash=2000)
        second.state = TaskStateType.DONE

        assert await store.add_tasks([first]) == 1
        assert await store.add_tasks([second]) == 1

        saved = await store.get_task(7)
        assert saved.name == "second"
        assert saved.state == TaskStateType.DONE
        assert saved.commission == 0.002
        assert [task.id for task in await store.get_all_tasks()] == [7]
        assert await store.del_task(7) is True
        assert await store.get_task(7) is None

    asyncio.run(_with_db(run))


def test_availability_repository_keeps_earliest_known_open_time_monotonic():
    async def run():
        store = AvailabilityCol(_Log())

        assert await store.get_earliest_known_open_time("BINANCE", "BTCUSDT", "1h") is None
        assert await store.update_earliest_known_open_time("BINANCE", "BTCUSDT", "1h", 100, source="first") is True
        assert await store.update_earliest_known_open_time("BINANCE", "BTCUSDT", "1h", 200, source="later") is False
        assert await store.update_earliest_known_open_time("BINANCE", "BTCUSDT", "1h", 50, source="earlier") is True

        state = await store.get_state("BINANCE", "BTCUSDT", "1h")
        assert state.earliest_known_open_time == 50
        assert state.source == "earlier"

    asyncio.run(_with_db(run))


def test_availability_state_handles_legacy_rows_without_cached_range_fields():
    state = model_to_availability_state(
        SimpleNamespace(
            exchange="BINANCE",
            symbol="BTCUSDT",
            interval="1h",
            earliest_known_open_time=100,
            updated_at=100,
            source="legacy",
        )
    )

    assert state.earliest_known_open_time == 100
    assert state.cached_start_open_time is None
    assert state.cached_end_open_time is None


def test_availability_repository_merges_cached_open_time_range():
    async def run():
        store = AvailabilityCol(_Log())

        assert await store.get_cached_open_time_range("BINANCE", "BTCUSDT", "1h") is None
        assert await store.update_cached_open_time_range("BINANCE", "BTCUSDT", "1h", 100, 200, source="first") is True
        assert await store.update_cached_open_time_range("BINANCE", "BTCUSDT", "1h", 120, 180, source="inside") is False
        assert await store.update_cached_open_time_range("BINANCE", "BTCUSDT", "1h", 50, 250, source="extend") is True

        assert await store.get_earliest_known_open_time("BINANCE", "BTCUSDT", "1h") is None
        assert await store.get_cached_open_time_range("BINANCE", "BTCUSDT", "1h") == (50, 250)
        state = await store.get_state("BINANCE", "BTCUSDT", "1h")
        assert state.cached_start_open_time == 50
        assert state.cached_end_open_time == 250
        assert state.source == "extend"

    asyncio.run(_with_db(run))
