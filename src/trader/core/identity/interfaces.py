"""Outbound ports for the identity context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Protocol, runtime_checkable

from trader.core.identity.domain import Session, User


class UserRepository(ABC):
    @abstractmethod
    async def create_user(
        self,
        username: str,
        password_hash: str,
        *,
        role: str = "user",
        status: str = "active",
        must_change_password: bool = False,
    ) -> User: ...

    @abstractmethod
    async def get_by_username(self, username: str) -> User | None: ...

    @abstractmethod
    async def get_by_id(self, user_id: int) -> User | None: ...

    @abstractmethod
    async def count_admins(self) -> int: ...

    @abstractmethod
    async def get_first_admin(self) -> User | None: ...

    @abstractmethod
    async def list_users(self) -> list[User]: ...

    @abstractmethod
    async def update_password(self, user_id: int, password_hash: str, *, must_change_password: bool) -> bool: ...

    @abstractmethod
    async def mark_login(self, user_id: int, when: datetime) -> bool: ...


class SessionRepository(ABC):
    @abstractmethod
    async def create_session(self, user_id: int, session_hash: str, expires_at: datetime) -> Session: ...

    @abstractmethod
    async def get_session(self, session_hash: str) -> Session | None: ...

    @abstractmethod
    async def delete_session(self, session_hash: str) -> bool: ...

    @abstractmethod
    async def delete_sessions_for_user(self, user_id: int) -> int: ...


class PasswordHasher(ABC):
    @abstractmethod
    def hash(self, password: str) -> str: ...

    @abstractmethod
    def verify(self, password: str, password_hash: str) -> bool: ...


class SecretCipher(ABC):
    @abstractmethod
    def encrypt(self, value: str) -> str: ...

    @abstractmethod
    def decrypt(self, encrypted_value: str) -> str: ...


@runtime_checkable
class SecretCipherFactory(Protocol):
    def __call__(self, service_key: str | None) -> SecretCipher | None: ...
