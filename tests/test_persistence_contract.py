"""Repository contract suite run against Tortoise (temporary SQLite) and in-memory fakes."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import pytest

from tests.persistence_harness import (
    InMemoryKlineRepository,
    InMemoryTaskRepository,
    initialized_database,
)
from trader.adapters.outbound.persistence.kline import KlineCol
from trader.adapters.outbound.persistence.task import TaskCol
from trader.core.shared.domain import Kline
from trader.utils.task_state import TaskState, TaskStateType

ADAPTERS = ("tortoise", "in_memory")


class _Log:
    def debug(self, *_args, **_kwargs):
        pass

    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


@asynccontextmanager
async def _kline_repository(adapter: str, db_path: Path):
    if adapter == "tortoise":
        async with initialized_database(f"sqlite://{db_path}"):
            yield KlineCol(_Log())
    else:
        yield InMemoryKlineRepository()


@asynccontextmanager
async def _task_repository(adapter: str, db_path: Path):
    if adapter == "tortoise":
        async with initialized_database(f"sqlite://{db_path}"):
            yield TaskCol(_Log())
    else:
        yield InMemoryTaskRepository()


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


def _task(task_id: int, name: str, *, user_id: int | None = None, state: TaskStateType = TaskStateType.READY, error_message=None):
    task = TaskState(
        task_id,
        name,
        datetime(2026, 1, 1),
        commission=0.001,
        initial_cash=1000,
        user_id=user_id,
        error_message=error_message,
    )
    task.state = state
    return task


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_kline_repository_contract(adapter: str, tmp_path: Path):
    asyncio.run(_kline_contract(adapter, tmp_path / "klines.db"))


async def _kline_contract(adapter: str, db_path: Path) -> None:
    async with _kline_repository(adapter, db_path) as store:
        inserted = await store.add_klines(
            "BTCUSDT-1h",
            [_kline(3600, 102.0), _kline(0, 100.0), _kline(7200, 104.0), _kline(3600, 102.0)],
            raw_payloads=[{"raw": 1}, {"raw": 2}, {"raw": 3}, {"raw": 4}],
            source="test",
        )
        assert inserted == 3
        assert await store.add_klines("BTCUSDT-1h", [_kline(3600, 102.0)]) == 0

        assert (await store.get_first_kline("BTCUSDT-1h")).open_time == 0
        assert (await store.get_latest_kline("BTCUSDT-1h")).open_time == 7200
        assert (await store.get_kline("BTCUSDT-1h", 3600)).open_time == 3600
        assert [row.open_time for row in await store.get_all_klines("BTCUSDT-1h")] == [0, 3600, 7200]
        assert [row.open_time for row in await store.get_klines("BTCUSDT-1h")] == [0, 3600, 7200]
        assert [row.open_time for row in await store.get_klines("BTCUSDT-1h", 1, 7200)] == [3600, 7200]
        assert [row.open_time for row in await store.get_klines("BTCUSDT-1h", 7200, 1)] == [0, 3600, 7200]
        assert [row.open_time for row in await store.get_latest_klines("BTCUSDT-1h", 2)] == [3600, 7200]
        assert await store.get_all_klines("ETHUSDT-1h") == []

        assert await store.delete_klines_in_range("BTCUSDT-1h", 3600, 3600) == 1
        assert [row.open_time for row in await store.get_all_klines("BTCUSDT-1h")] == [0, 7200]
        assert await store.get_kline("BTCUSDT-1h", 3600) is None

        with pytest.raises(ValueError):
            await store.get_latest_kline("BTCUSDT")


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_task_repository_contract(adapter: str, tmp_path: Path):
    asyncio.run(_task_contract(adapter, tmp_path / "tasks.db"))


async def _task_contract(adapter: str, db_path: Path) -> None:
    async with _task_repository(adapter, db_path) as store:
        assert await store.get_task(7) is None
        assert await store.add_tasks([_task(7, "first", user_id=10, state=TaskStateType.RUNNING)]) == 1
        assert await store.add_tasks([_task(7, "second", user_id=10, state=TaskStateType.DONE)]) == 1
        failed = _task(8, "failed", user_id=20, state=TaskStateType.FAILED, error_message="startup failed")
        assert await store.add_tasks([failed]) == 1

        saved = await store.get_task(7)
        assert saved.name == "second"
        assert saved.state == TaskStateType.DONE
        assert saved.user_id == 10
        assert (await store.get_task(8)).error_message == "startup failed"
        assert await store.get_task_for_user(7, 10) is not None
        assert await store.get_task_for_user(7, 20) is None

        assert [task.id for task in await store.get_all_tasks()] == [7, 8]
        assert [task.id for task in await store.get_all_tasks_for_user(20)] == [8]
        assert await store.get_all_tasks_for_user(99) == []

        assert await store.del_task(7) is True
        assert await store.del_task(7) is False
        assert await store.get_task(7) is None
