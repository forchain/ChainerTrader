import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from tests.persistence_harness import InMemoryIdentityRepository
from trader.core.identity.exceptions import AuthenticationError, CredentialEncryptionError, PasswordPolicyError
from trader.core.identity.passwords import validate_password
from trader.core.identity.sessions import hash_session_token
from trader.core.identity.use_cases import (
    BootstrapAdministrator,
    ChangePassword,
    DecryptUserCredential,
    EncryptUserCredential,
    LoginUser,
    LogoutUser,
    RegisterUser,
    ResetUserPassword,
    ValidateSession,
)


class FakePasswordHasher:
    def hash(self, password: str) -> str:
        return f"hashed::{password}"

    def verify(self, password: str, password_hash: str) -> bool:
        return password_hash == self.hash(password)


class FakeSecretCipher:
    def encrypt(self, value: str) -> str:
        return f"encrypted::{value}"

    def decrypt(self, encrypted_value: str) -> str:
        if not encrypted_value.startswith("encrypted::"):
            raise CredentialEncryptionError("cannot decrypt")
        return encrypted_value.removeprefix("encrypted::")


def _run(fn):
    asyncio.run(fn())


async def _create_user(users, username="trader", password="marketBot2026", *, status="active"):
    return await users.create_user(username, FakePasswordHasher().hash(password), role="user", status=status)


def test_bootstrap_administrator_creates_admin_from_configuration():
    async def run():
        users = InMemoryIdentityRepository()

        admin = await BootstrapAdministrator(users, FakePasswordHasher()).execute("admin", "AdminPass2026!")

        assert admin.username == "admin"
        assert admin.role == "admin"
        assert admin.password_hash == "hashed::AdminPass2026!"
        assert await users.count_admins() == 1

    _run(run)


def test_bootstrap_administrator_is_noop_without_configured_credentials():
    async def run():
        users = InMemoryIdentityRepository()

        assert await BootstrapAdministrator(users, FakePasswordHasher()).execute(None, None) is None
        assert await users.list_users() == []

    _run(run)


def test_bootstrap_administrator_reuses_the_existing_admin():
    async def run():
        users = InMemoryIdentityRepository()
        existing = await users.create_user("existing-admin", "hash", role="admin")

        admin = await BootstrapAdministrator(users, FakePasswordHasher()).execute("admin", "AdminPass2026!")

        assert admin.id == existing.id
        assert await users.count_admins() == 1

    _run(run)


def test_bootstrap_administrator_rejects_weak_credentials():
    async def run():
        users = InMemoryIdentityRepository()

        with pytest.raises(PasswordPolicyError):
            await BootstrapAdministrator(users, FakePasswordHasher()).execute("admin", "password123")

    _run(run)


def test_login_creates_a_hashed_session_and_marks_last_login():
    async def run():
        users = InMemoryIdentityRepository()
        user = await _create_user(users)
        now = datetime.now(UTC)

        result = await LoginUser(users, users, FakePasswordHasher()).execute(user.username, "marketBot2026", session_ttl_hours=24, now=now)

        assert result.user.id == user.id
        assert result.expires_at == now + timedelta(hours=24)
        session = await users.get_session(hash_session_token(result.session_token))
        assert session.user_id == user.id
        assert (await users.get_by_id(user.id)).last_login_at == now

    _run(run)


@pytest.mark.parametrize(("password", "status"), [("wrong-password", "active"), ("marketBot2026", "disabled")])
def test_login_rejects_bad_credentials_or_inactive_users(password, status):
    async def run():
        users = InMemoryIdentityRepository()
        user = await _create_user(users, status=status)

        with pytest.raises(AuthenticationError):
            await LoginUser(users, users, FakePasswordHasher()).execute(user.username, password, session_ttl_hours=24)

    _run(run)


def test_validate_session_returns_the_active_user():
    async def run():
        users = InMemoryIdentityRepository()
        user = await _create_user(users)
        expires_at = datetime.now(UTC) + timedelta(hours=1)
        await users.create_session(user.id, hash_session_token("token"), expires_at)

        assert (await ValidateSession(users, users).execute("token")).id == user.id
        assert await ValidateSession(users, users).execute(None) is None
        assert await ValidateSession(users, users).execute("unknown") is None

    _run(run)


def test_validate_session_rejects_expired_sessions():
    async def run():
        users = InMemoryIdentityRepository()
        user = await _create_user(users)
        await users.create_session(user.id, hash_session_token("token"), datetime.now(UTC) - timedelta(seconds=1))

        assert await ValidateSession(users, users).execute("token") is None

    _run(run)


def test_logout_deletes_the_session():
    async def run():
        users = InMemoryIdentityRepository()
        user = await _create_user(users)
        await users.create_session(user.id, hash_session_token("token"), datetime.now(UTC) + timedelta(hours=1))

        await LogoutUser(users).execute("token")

        assert await users.get_session(hash_session_token("token")) is None

    _run(run)


def test_register_user_enforces_policy_and_unique_usernames():
    async def run():
        users = InMemoryIdentityRepository()

        created = await RegisterUser(users, FakePasswordHasher()).execute("new-user", "marketBot2026")
        assert created.role == "user"

        with pytest.raises(AuthenticationError):
            await RegisterUser(users, FakePasswordHasher()).execute("new-user", "anotherPass2026")

        with pytest.raises(PasswordPolicyError):
            await RegisterUser(users, FakePasswordHasher()).execute("other-user", "short")

    _run(run)


def test_change_password_validates_policy_and_updates_the_hash():
    async def run():
        users = InMemoryIdentityRepository()
        user = await _create_user(users)

        assert await ChangePassword(users, FakePasswordHasher()).execute(user.id, user.username, "newPassword2026") is True
        assert (await users.get_by_id(user.id)).password_hash == "hashed::newPassword2026"

        with pytest.raises(PasswordPolicyError):
            await ChangePassword(users, FakePasswordHasher()).execute(user.id, user.username, "short")

    _run(run)


def test_reset_password_issues_a_temporary_password_and_revokes_sessions():
    async def run():
        users = InMemoryIdentityRepository()
        user = await _create_user(users)
        await users.create_session(user.id, "first", datetime.now(UTC) + timedelta(hours=1))
        await users.create_session(user.id, "second", datetime.now(UTC) + timedelta(hours=1))

        temporary_password = await ResetUserPassword(users, users, FakePasswordHasher()).execute(user.id)

        validate_password(user.username, temporary_password)
        updated = await users.get_by_id(user.id)
        assert updated.password_hash == FakePasswordHasher().hash(temporary_password)
        assert updated.must_change_password is True
        assert await users.get_session("first") is None
        assert await users.get_session("second") is None

        with pytest.raises(AuthenticationError):
            await ResetUserPassword(users, users, FakePasswordHasher()).execute(999)

    _run(run)


def test_user_credentials_are_encrypted_decrypted_and_masked():
    async def run():
        cipher = FakeSecretCipher()

        protected = EncryptUserCredential(cipher).execute("abcdef123456", "super-secret")

        assert protected.encrypted_api_key == "encrypted::abcdef123456"
        assert protected.encrypted_api_secret == "encrypted::super-secret"
        assert protected.masked_api_key == "abcd***3456"

        plain = DecryptUserCredential(cipher).execute(protected.encrypted_api_key, protected.encrypted_api_secret)
        assert plain.api_key == "abcdef123456"
        assert plain.api_secret == "super-secret"

    _run(run)
