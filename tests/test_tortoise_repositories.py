import asyncio
import warnings
from datetime import UTC, datetime
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
        failed = TaskState(8, "failed", datetime(2026, 1, 3), error_message="startup failed")
        failed.state = TaskStateType.FAILED
        assert await store.add_tasks([failed]) == 1
        saved_failed = await store.get_task(8)
        assert saved_failed.state == TaskStateType.FAILED
        assert saved_failed.error_message == "startup failed"
        assert [task.id for task in await store.get_all_tasks()] == [7, 8]
        assert await store.del_task(7) is True
        assert await store.del_task(8) is True
        assert await store.get_task(7) is None
        assert await store.get_task(8) is None

    asyncio.run(_with_db(run))


def test_task_repository_normalizes_naive_start_time_before_write():
    async def run():
        store = TaskCol(_Log())
        state = TaskState(13, "timezone-safe", datetime(2026, 1, 8))

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert await store.add_tasks([state]) == 1

        messages = [str(item.message) for item in caught]
        assert not any("DateTimeField start_time received a naive datetime" in message for message in messages)

    asyncio.run(_with_db(run))


def test_model_to_task_state_tolerates_rows_without_error_message_field():
    row = type(
        "LegacyTaskStateRow",
        (),
        {
            "task_id": 9,
            "state": "RUNNING",
            "name": "legacy",
            "start_time": datetime(2026, 1, 4),
            "commission": 0.001,
            "initial_cash": 1000,
            "config_json": None,
            "tret": None,
            "user_id": None,
            "strategy_start_time": 0,
            "strategy_end_time": 0,
        },
    )()

    from trader.database.task import model_to_task_state

    state = model_to_task_state(row)

    assert state.id == 9
    assert state.error_message is None


def test_task_repository_upsert_avoids_partial_model_save(monkeypatch):
    calls = []

    class _Query:
        async def update(self, **defaults):
            calls.append(("update", defaults))
            return 1

    class _Model:
        @classmethod
        def filter(cls, **kwargs):
            calls.append(("filter", kwargs))
            return _Query()

        @classmethod
        async def create(cls, **_kwargs):
            raise AssertionError("create should not run when update succeeds")

        @classmethod
        async def update_or_create(cls, **_kwargs):
            raise AssertionError("update_or_create would save partial models")

    monkeypatch.setattr("trader.database.task.TaskStateModel", _Model)
    state = TaskState(10, "partial-safe", datetime(2026, 1, 5))

    assert asyncio.run(TaskCol(_Log()).add_tasks([state])) == 1
    assert calls[0] == ("filter", {"task_id": 10})
    assert calls[1][0] == "update"
    assert calls[1][1]["state"] == "READY"


def test_task_repository_retries_without_error_message_for_legacy_schema(monkeypatch):
    calls = []

    class _Query:
        async def update(self, **defaults):
            calls.append(("update", defaults))
            if "error_message" in defaults:
                raise Exception("no such column: error_message")
            return 1

    class _Model:
        _meta = SimpleNamespace(fields_map={"error_message": object()})

        @classmethod
        def filter(cls, **kwargs):
            calls.append(("filter", kwargs))
            return _Query()

        @classmethod
        async def create(cls, **_kwargs):
            raise AssertionError("create should not run when update retry succeeds")

    state = TaskState(11, "legacy-schema", datetime(2026, 1, 6), error_message="startup failed")
    state.state = TaskStateType.FAILED
    monkeypatch.setattr("trader.database.task.TaskStateModel", _Model)

    assert asyncio.run(TaskCol(_Log()).add_tasks([state])) == 1
    assert calls[1] == (
        "update",
        {
            "state": "FAILED",
            "user_id": None,
            "name": "legacy-schema",
            "start_time": datetime(2026, 1, 6, tzinfo=UTC),
            "commission": 0,
            "strategy_start_time": 0,
            "strategy_end_time": 0,
            "initial_cash": 0,
            "config_json": None,
            "tret": None,
            "error_message": "startup failed",
        },
    )
    assert calls[3][0] == "update"
    assert "error_message" not in calls[3][1]


def test_task_repository_creates_failed_state_without_error_message_for_legacy_schema():
    async def run():
        from tortoise import connections

        connection = connections.get("default")
        await connection.execute_script(
            """
            DROP TABLE "tasks";
            CREATE TABLE "tasks" (
                "task_id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                "user_id" INT,
                "state" VARCHAR(32) NOT NULL,
                "name" VARCHAR(255),
                "start_time" TIMESTAMP NOT NULL,
                "commission" REAL NOT NULL,
                "strategy_start_time" INT NOT NULL,
                "strategy_end_time" INT NOT NULL,
                "initial_cash" REAL NOT NULL,
                "config_json" TEXT,
                "tret" JSON
            );
            """
        )
        store = TaskCol(_Log())
        failed = TaskState(12, "legacy-create", datetime(2026, 1, 7), error_message="startup failed")
        failed.state = TaskStateType.FAILED

        assert await store.add_tasks([failed]) == 1
        _, rows = await connection.execute_query('SELECT task_id, state, name FROM "tasks" WHERE task_id = ?', [12])
        assert rows[0]["state"] == "FAILED"
        assert rows[0]["name"] == "legacy-create"

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
