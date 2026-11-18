"""Identity domain values: users, sessions, and roles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from trader.core.identity.sessions import is_expired


class Role(str, Enum):
    ADMIN = "admin"
    USER = "user"


class UserStatus(str, Enum):
    ACTIVE = "active"


@dataclass(frozen=True)
class User:
    id: int | None
    username: str
    password_hash: str
    role: str = Role.USER.value
    status: str = UserStatus.ACTIVE.value
    must_change_password: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_login_at: datetime | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE


@dataclass(frozen=True)
class Session:
    id: int | None
    user_id: int
    session_hash: str
    expires_at: datetime
    created_at: datetime | None = None

    def is_expired(self) -> bool:
        return is_expired(self.expires_at)
