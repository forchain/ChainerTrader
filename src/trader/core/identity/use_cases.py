"""Identity use cases: administrator bootstrap, login sessions, passwords, and credentials."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from trader.core.identity.credentials import mask_api_key
from trader.core.identity.domain import Role, User
from trader.core.identity.exceptions import AuthenticationError
from trader.core.identity.interfaces import PasswordHasher, SecretCipher, SessionRepository, UserRepository
from trader.core.identity.passwords import generate_temporary_password, validate_password, validate_username
from trader.core.identity.sessions import create_session_token, hash_session_token, is_expired


@dataclass(frozen=True)
class LoginResult:
    user: User
    session_token: str
    expires_at: datetime


@dataclass(frozen=True)
class ProtectedCredential:
    encrypted_api_key: str
    encrypted_api_secret: str
    masked_api_key: str


@dataclass(frozen=True)
class PlainCredential:
    api_key: str
    api_secret: str


class BootstrapAdministrator:
    """Create the configured administrator once, or return the existing first admin."""

    def __init__(self, users: UserRepository, password_hasher: PasswordHasher):
        self.users = users
        self.password_hasher = password_hasher

    async def execute(self, username: str | None, password: str | None) -> User | None:
        if not username or not password:
            return None
        if await self.users.count_admins() > 0:
            return await self.users.get_first_admin()
        validate_username(username)
        validate_password(username, password)
        return await self.users.create_user(username, self.password_hasher.hash(password), role=Role.ADMIN.value)


class LoginUser:
    def __init__(self, users: UserRepository, sessions: SessionRepository, password_hasher: PasswordHasher):
        self.users = users
        self.sessions = sessions
        self.password_hasher = password_hasher

    async def execute(self, username: str, password: str, *, session_ttl_hours: int, now: datetime | None = None) -> LoginResult:
        user = await self.users.get_by_username(username)
        if user is None or not user.is_active or not self.password_hasher.verify(password, user.password_hash):
            raise AuthenticationError("invalid username or password")
        current_time = now or datetime.now(UTC)
        expires_at = current_time + timedelta(hours=int(session_ttl_hours))
        token = create_session_token()
        await self.sessions.create_session(user.id, hash_session_token(token), expires_at)
        await self.users.mark_login(user.id, current_time)
        return LoginResult(user=user, session_token=token, expires_at=expires_at)


class LogoutUser:
    def __init__(self, sessions: SessionRepository):
        self.sessions = sessions

    async def execute(self, token: str | None) -> None:
        if token:
            await self.sessions.delete_session(hash_session_token(token))


class ValidateSession:
    def __init__(self, users: UserRepository, sessions: SessionRepository):
        self.users = users
        self.sessions = sessions

    async def execute(self, token: str | None) -> User | None:
        if not token:
            return None
        session = await self.sessions.get_session(hash_session_token(token))
        if session is None or is_expired(session.expires_at):
            return None
        user = await self.users.get_by_id(session.user_id)
        if user is None or user.status != "active":
            return None
        return user


class RegisterUser:
    def __init__(self, users: UserRepository, password_hasher: PasswordHasher):
        self.users = users
        self.password_hasher = password_hasher

    async def execute(self, username: str, password: str) -> User:
        validate_username(username)
        validate_password(username, password)
        if await self.users.get_by_username(username) is not None:
            raise AuthenticationError("username already exists")
        return await self.users.create_user(username, self.password_hasher.hash(password), role=Role.USER.value)


class ChangePassword:
    def __init__(self, users: UserRepository, password_hasher: PasswordHasher):
        self.users = users
        self.password_hasher = password_hasher

    async def execute(self, user_id: int, username: str, password: str) -> bool:
        validate_password(username, password)
        return await self.users.update_password(user_id, self.password_hasher.hash(password), must_change_password=False)


class ResetUserPassword:
    """Administrator reset: issue a temporary password and invalidate existing sessions."""

    def __init__(self, users: UserRepository, sessions: SessionRepository, password_hasher: PasswordHasher):
        self.users = users
        self.sessions = sessions
        self.password_hasher = password_hasher

    async def execute(self, user_id: int) -> str:
        if await self.users.get_by_id(user_id) is None:
            raise AuthenticationError("user not found")
        temporary_password = generate_temporary_password()
        await self.users.update_password(user_id, self.password_hasher.hash(temporary_password), must_change_password=True)
        await self.sessions.delete_sessions_for_user(user_id)
        return temporary_password


class EncryptUserCredential:
    def __init__(self, cipher: SecretCipher):
        self.cipher = cipher

    def execute(self, api_key: str, api_secret: str) -> ProtectedCredential:
        return ProtectedCredential(
            encrypted_api_key=self.cipher.encrypt(api_key),
            encrypted_api_secret=self.cipher.encrypt(api_secret),
            masked_api_key=mask_api_key(api_key),
        )


class DecryptUserCredential:
    def __init__(self, cipher: SecretCipher):
        self.cipher = cipher

    def execute(self, encrypted_api_key: str, encrypted_api_secret: str) -> PlainCredential:
        return PlainCredential(
            api_key=self.cipher.decrypt(encrypted_api_key),
            api_secret=self.cipher.decrypt(encrypted_api_secret),
        )
