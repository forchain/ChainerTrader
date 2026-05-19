from __future__ import annotations

from datetime import datetime
from logging import Logger

from trader.database.models import SessionModel, UserModel


class UserCol:
    def __init__(self, log: Logger):
        self.log = log

    async def create_user(
        self,
        username: str,
        password_hash: str,
        *,
        role: str = "user",
        status: str = "active",
        must_change_password: bool = False,
    ) -> UserModel:
        return await UserModel.create(
            username=username,
            password_hash=password_hash,
            role=role,
            status=status,
            must_change_password=must_change_password,
        )

    async def get_by_username(self, username: str) -> UserModel | None:
        return await UserModel.filter(username=username).first()

    async def get_by_id(self, user_id: int) -> UserModel | None:
        return await UserModel.filter(id=user_id).first()

    async def count_admins(self) -> int:
        return await UserModel.filter(role="admin").count()

    async def list_users(self) -> list[UserModel]:
        return await UserModel.all().order_by("id")

    async def update_password(self, user_id: int, password_hash: str, *, must_change_password: bool) -> bool:
        updated = await UserModel.filter(id=user_id).update(
            password_hash=password_hash,
            must_change_password=must_change_password,
        )
        return updated == 1

    async def mark_login(self, user_id: int, when: datetime) -> bool:
        updated = await UserModel.filter(id=user_id).update(last_login_at=when)
        return updated == 1

    async def create_session(self, user_id: int, session_hash: str, expires_at: datetime) -> SessionModel:
        return await SessionModel.create(user_id=user_id, session_hash=session_hash, expires_at=expires_at)

    async def get_session(self, session_hash: str) -> SessionModel | None:
        return await SessionModel.filter(session_hash=session_hash).first()

    async def delete_session(self, session_hash: str) -> bool:
        deleted = await SessionModel.filter(session_hash=session_hash).delete()
        return deleted > 0
