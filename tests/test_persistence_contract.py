"""Repository contract suite run against Tortoise (temporary SQLite) and in-memory fakes."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.persistence_harness import (
    InMemoryIdentityRepository,
    InMemoryKlineRepository,
    InMemoryTaskRepository,
    initialized_database,
)
from trader.adapters.outbound.persistence.kline import KlineCol
from trader.adapters.outbound.persistence.task import TaskCol
from trader.adapters.outbound.persistence.user import UserCol
from trader.core.shared.domain import Kline
from trader.core.task.domain import TaskState, TaskStateType
from trader.core.task.interfaces import TaskRepository

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


@asynccontextmanager
async def _identity_repository(adapter: str, db_path: Path):
    if adapter == "tortoise":
        async with initialized_database(f"sqlite://{db_path}"):
            yield UserCol(_Log())
    else:
        yield InMemoryIdentityRepository()


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
        assert isinstance(store, TaskRepository)
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


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_identity_repository_contract(adapter: str, tmp_path: Path):
    asyncio.run(_identity_contract(adapter, tmp_path / "identity.db"))


async def _identity_contract(adapter: str, db_path: Path) -> None:
    async with _identity_repository(adapter, db_path) as users:
        assert await users.count_admins() == 0
        assert await users.get_by_username("admin") is None
        assert await users.get_first_admin() is None
        assert await users.list_users() == []

        trader = await users.create_user("trader", "hash-1", role="user")
        admin = await users.create_user("admin", "hash-2", role="admin")

        assert trader.id is not None
        assert trader.role == "user"
        assert trader.status == "active"
        assert trader.must_change_password is False
        assert await users.count_admins() == 1
        assert (await users.get_first_admin()).id == admin.id
        assert [user.username for user in await users.list_users()] == ["trader", "admin"]
        assert (await users.get_by_username("trader")).id == trader.id
        assert (await users.get_by_id(trader.id)).password_hash == "hash-1"

        when = datetime.now(UTC)
        assert await users.mark_login(trader.id, when) is True
        assert (await users.get_by_id(trader.id)).last_login_at is not None
        assert await users.update_password(trader.id, "hash-3", must_change_password=True) is True
        updated = await users.get_by_id(trader.id)
        assert updated.password_hash == "hash-3"
        assert updated.must_change_password is True
        assert await users.update_password(999, "hash-x", must_change_password=True) is False
        assert await users.mark_login(999, when) is False

        expires_at = datetime.now(UTC) + timedelta(hours=1)
        session = await users.create_session(trader.id, "session-1", expires_at)
        assert session.id is not None
        assert (await users.get_session("session-1")).user_id == trader.id
        assert await users.get_session("unknown") is None
        assert await users.delete_session("session-1") is True
        assert await users.delete_session("session-1") is False

        await users.create_session(trader.id, "first-session-1", expires_at)
        await users.create_session(trader.id, "first-session-2", expires_at)
        await users.create_session(admin.id, "second-session", expires_at)
        assert await users.delete_sessions_for_user(trader.id) == 2
        assert await users.get_session("first-session-1") is None
        assert await users.get_session("first-session-2") is None
        assert await users.get_session("second-session") is not None
