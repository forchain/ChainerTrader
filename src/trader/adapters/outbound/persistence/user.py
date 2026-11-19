from __future__ import annotations

from datetime import datetime
from logging import Logger

from trader.adapters.outbound.persistence.models import SessionModel, UserModel
from trader.core.identity.domain import Role, Session, User
from trader.core.identity.interfaces import SessionRepository, UserRepository


def _user(row: UserModel) -> User:
    return User(
        id=row.id,
        username=row.username,
        password_hash=row.password_hash,
        role=row.role,
        status=row.status,
        must_change_password=row.must_change_password,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_login_at=row.last_login_at,
    )


def _session(row: SessionModel) -> Session:
    return Session(
        id=row.id,
        user_id=row.user_id,
        session_hash=row.session_hash,
        expires_at=row.expires_at,
        created_at=row.created_at,
    )


class UserCol(UserRepository, SessionRepository):
    def __init__(self, log: Logger):
        self.log = log

    async def create_user(
        self,
        username: str,
        password_hash: str,
        *,
        role: str = Role.USER.value,
        status: str = "active",
        must_change_password: bool = False,
    ) -> User:
        row = await UserModel.create(
            username=username,
            password_hash=password_hash,
            role=role,
            status=status,
            must_change_password=must_change_password,
        )
        return _user(row)

    async def get_by_username(self, username: str) -> User | None:
        row = await UserModel.filter(username=username).first()
        return _user(row) if row is not None else None

    async def get_by_id(self, user_id: int) -> User | None:
        row = await UserModel.filter(id=user_id).first()
        return _user(row) if row is not None else None

    async def count_admins(self) -> int:
        return await UserModel.filter(role=Role.ADMIN.value).count()

    async def get_first_admin(self) -> User | None:
        row = await UserModel.filter(role=Role.ADMIN.value, status="active").order_by("id").first()
        return _user(row) if row is not None else None

    async def list_users(self) -> list[User]:
        return [_user(row) for row in await UserModel.all().order_by("id")]

    async def update_password(self, user_id: int, password_hash: str, *, must_change_password: bool) -> bool:
        updated = await UserModel.filter(id=user_id).update(
            password_hash=password_hash,
            must_change_password=must_change_password,
        )
        return updated == 1

    async def mark_login(self, user_id: int, when: datetime) -> bool:
        updated = await UserModel.filter(id=user_id).update(last_login_at=when)
        return updated == 1

    async def create_session(self, user_id: int, session_hash: str, expires_at: datetime) -> Session:
        row = await SessionModel.create(user_id=user_id, session_hash=session_hash, expires_at=expires_at)
        return _session(row)

    async def get_session(self, session_hash: str) -> Session | None:
        row = await SessionModel.filter(session_hash=session_hash).first()
        return _session(row) if row is not None else None

    async def delete_session(self, session_hash: str) -> bool:
        deleted = await SessionModel.filter(session_hash=session_hash).delete()
        return deleted > 0

    async def delete_sessions_for_user(self, user_id: int) -> int:
        return await SessionModel.filter(user_id=user_id).delete()
