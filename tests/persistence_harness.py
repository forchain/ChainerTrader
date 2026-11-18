"""Shared persistence test harness: real temporary SQLite database and in-memory fakes.

The contract suite in ``test_persistence_contract.py`` exercises the same operations
through the Tortoise-backed repositories and these fakes, proving their equivalence.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime

from tortoise import Tortoise

from trader.adapters.outbound.persistence.config import build_tortoise_config
from trader.adapters.outbound.persistence.kline import DEFAULT_EXCHANGE, split_symbol_interval
from trader.core.execution import ExecutionStateRecord, ExecutionStateReservation, ExecutionStatus
from trader.core.identity.domain import Session, User
from trader.core.shared.domain import Kline
from trader.utils.task_state import TaskState, parse_task_state

KlineKey = tuple[str, str, str, int]

TERMINAL_EXECUTION_STATUSES = {
    ExecutionStatus.CANCELED,
    ExecutionStatus.REJECTED,
    ExecutionStatus.SKIPPED,
    ExecutionStatus.FAILED,
}


@asynccontextmanager
async def initialized_database(db_url: str = "sqlite://:memory:"):
    """Initialize a temporary database with the production schema."""
    await Tortoise.init(config=build_tortoise_config(db_url))
    await Tortoise.generate_schemas()
    try:
        yield
    finally:
        await Tortoise.close_connections()


def _copy_kline(row: Kline) -> Kline:
    return Kline(
        open_time=row.open_time,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        close_time=row.close_time,
        volume=row.volume,
        vol_quote=row.vol_quote,
        trades=row.trades,
        vol_taker_base=row.vol_taker_base,
        vol_taker_quote=row.vol_taker_quote,
        ignore=row.ignore,
    )


class InMemoryKlineRepository:
    """Fake kline repository mirroring ``KlineCol`` observable behavior."""

    def __init__(self, exchange: str = DEFAULT_EXCHANGE):
        self.exchange = exchange
        self._rows: dict[KlineKey, Kline] = {}

    def _key(self, name: str, open_time: int) -> KlineKey:
        symbol, interval = split_symbol_interval(name)
        return self.exchange, symbol, interval, open_time

    async def add_klines(self, name: str, klines: list[Kline], raw_payloads=None, source: str = "unknown") -> int:
        if len(klines) <= 0:
            return 0
        total = 0
        seen: set[int] = set()
        for row in klines:
            if row.open_time in seen:
                continue
            seen.add(row.open_time)
            key = self._key(name, row.open_time)
            if key not in self._rows:
                self._rows[key] = _copy_kline(row)
                total += 1
        return total

    async def get_latest_kline(self, name: str) -> Kline | None:
        rows = self._matching(name)
        if not rows:
            return None
        return _copy_kline(max(rows, key=lambda row: row.open_time))

    async def get_latest_klines(self, name: str, limit: int) -> list[Kline] | None:
        rows = sorted(self._matching(name), key=lambda row: row.open_time, reverse=True)[:limit]
        klines = [_copy_kline(row) for row in rows]
        if len(klines) > 1:
            klines.reverse()
        return klines

    async def get_first_kline(self, name: str) -> Kline | None:
        rows = self._matching(name)
        if not rows:
            return None
        return _copy_kline(min(rows, key=lambda row: row.open_time))

    async def get_kline(self, name: str, open_time: int) -> Kline | None:
        row = self._rows.get(self._key(name, open_time))
        return _copy_kline(row) if row is not None else None

    async def get_all_klines(self, name: str) -> list[Kline] | None:
        return [_copy_kline(row) for row in sorted(self._matching(name), key=lambda row: row.open_time)]

    async def get_klines(self, name: str, start_time: int = 0, end_time: int = 0) -> list[Kline] | None:
        if start_time == 0 and end_time == 0:
            return await self.get_all_klines(name)
        if start_time > end_time and end_time > 0:
            return await self.get_all_klines(name)
        rows = self._matching(name)
        if start_time != 0:
            rows = [row for row in rows if row.open_time >= start_time]
        if end_time != 0:
            rows = [row for row in rows if row.open_time <= end_time]
        return [_copy_kline(row) for row in sorted(rows, key=lambda row: row.open_time)]

    async def delete_klines_in_range(self, name: str, start_time: int, end_time: int) -> int:
        keys = [key for key in self._matching_keys(name) if start_time <= key[3] <= end_time]
        for key in keys:
            del self._rows[key]
        return len(keys)

    def _matching_keys(self, name: str) -> list[KlineKey]:
        symbol, interval = split_symbol_interval(name)
        prefix = (self.exchange, symbol, interval)
        return [key for key in self._rows if key[:3] == prefix]

    def _matching(self, name: str) -> list[Kline]:
        return [self._rows[key] for key in self._matching_keys(name)]


class InMemoryIdentityRepository:
    """Fake user/session repository mirroring ``UserCol`` observable behavior."""

    def __init__(self):
        self._users: dict[int, User] = {}
        self._sessions: dict[str, Session] = {}
        self._next_user_id = 1
        self._next_session_id = 1

    async def create_user(
        self,
        username: str,
        password_hash: str,
        *,
        role: str = "user",
        status: str = "active",
        must_change_password: bool = False,
    ) -> User:
        now = datetime.now(UTC)
        user = User(
            id=self._next_user_id,
            username=username,
            password_hash=password_hash,
            role=role,
            status=status,
            must_change_password=must_change_password,
            created_at=now,
            updated_at=now,
        )
        self._next_user_id += 1
        self._users[user.id] = user
        return user

    async def get_by_username(self, username: str) -> User | None:
        return next((user for user in self._users.values() if user.username == username), None)

    async def get_by_id(self, user_id: int) -> User | None:
        return self._users.get(user_id)

    async def count_admins(self) -> int:
        return sum(1 for user in self._users.values() if user.role == "admin")

    async def get_first_admin(self) -> User | None:
        admins = [user for user in self._users.values() if user.role == "admin" and user.status == "active"]
        return min(admins, key=lambda user: user.id) if admins else None

    async def list_users(self) -> list[User]:
        return [self._users[user_id] for user_id in sorted(self._users)]

    async def update_password(self, user_id: int, password_hash: str, *, must_change_password: bool) -> bool:
        user = self._users.get(user_id)
        if user is None:
            return False
        self._users[user_id] = replace(user, password_hash=password_hash, must_change_password=must_change_password, updated_at=datetime.now(UTC))
        return True

    async def mark_login(self, user_id: int, when: datetime) -> bool:
        user = self._users.get(user_id)
        if user is None:
            return False
        self._users[user_id] = replace(user, last_login_at=when)
        return True

    async def create_session(self, user_id: int, session_hash: str, expires_at: datetime) -> Session:
        session = Session(
            id=self._next_session_id,
            user_id=user_id,
            session_hash=session_hash,
            expires_at=expires_at,
            created_at=datetime.now(UTC),
        )
        self._next_session_id += 1
        self._sessions[session_hash] = session
        return session

    async def get_session(self, session_hash: str) -> Session | None:
        return self._sessions.get(session_hash)

    async def delete_session(self, session_hash: str) -> bool:
        return self._sessions.pop(session_hash, None) is not None

    async def delete_sessions_for_user(self, user_id: int) -> int:
        hashes = [key for key, session in self._sessions.items() if session.user_id == user_id]
        for key in hashes:
            del self._sessions[key]
        return len(hashes)


class InMemoryTaskRepository:
    """Fake task repository mirroring ``TaskCol`` observable behavior."""

    def __init__(self):
        self._rows: dict[int, dict] = {}

    async def add_tasks(self, tasks: list[TaskState]) -> int:
        total = 0
        for state in tasks:
            self._rows[state.id] = state.to_dict()
            total += 1
        return total

    async def del_task(self, id: int) -> bool:
        return self._rows.pop(id, None) is not None

    async def get_task(self, id: int) -> TaskState | None:
        payload = self._rows.get(id)
        return parse_task_state(dict(payload)) if payload is not None else None

    async def get_task_for_user(self, id: int, user_id: int) -> TaskState | None:
        payload = self._rows.get(id)
        if payload is None or payload.get("user_id") != user_id:
            return None
        return parse_task_state(dict(payload))

    async def get_all_tasks(self) -> list[TaskState]:
        return [parse_task_state(dict(self._rows[key])) for key in sorted(self._rows)]

    async def get_all_tasks_for_user(self, user_id: int) -> list[TaskState]:
        return [
            parse_task_state(dict(self._rows[key]))
            for key in sorted(self._rows)
            if self._rows[key].get("user_id") == user_id
        ]


class InMemoryExecutionStateStore:
    """Fake execution state store mirroring ``ExecutionStateCol`` observable behavior."""

    def __init__(self):
        self._rows: dict[str, ExecutionStateRecord] = {}

    async def reserve(self, record: ExecutionStateRecord) -> ExecutionStateReservation:
        existing = self._rows.get(record.idempotency_key)
        if existing is not None:
            return ExecutionStateReservation(existing, created=False)
        return ExecutionStateReservation(await self.save(record), created=True)

    async def save(self, record: ExecutionStateRecord) -> ExecutionStateRecord:
        self._rows[record.idempotency_key] = record
        return record

    async def get_by_idempotency_key(self, idempotency_key: str) -> ExecutionStateRecord | None:
        return self._rows.get(idempotency_key)

    async def list_open_by_symbol(self, symbol: str) -> list[ExecutionStateRecord]:
        return self._open_records(record for record in self._rows.values() if record.symbol == symbol)

    async def list_open_by_task(self, task_id: int) -> list[ExecutionStateRecord]:
        return self._open_records(record for record in self._rows.values() if record.task_id == task_id)

    @staticmethod
    def _open_records(records) -> list[ExecutionStateRecord]:
        return sorted(
            (record for record in records if record.status not in TERMINAL_EXECUTION_STATUSES),
            key=lambda record: record.created_at,
        )
