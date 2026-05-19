import asyncio
from datetime import UTC, datetime, timedelta

from tortoise import Tortoise

from trader.database.config import build_tortoise_config
from trader.database.exchange_credential import ExchangeCredentialCol
from trader.database.strategy_config import StrategyConfigCol
from trader.database.user import UserCol


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


def test_user_repository_creates_and_updates_user():
    async def run():
        users = UserCol(_Log())

        user = await users.create_user("trader", "hash-1", role="user")
        saved = await users.get_by_username("trader")

        assert user.id is not None
        assert saved.id == user.id
        assert saved.role == "user"
        assert saved.must_change_password is False

        await users.update_password(user.id, "hash-2", must_change_password=True)
        updated = await users.get_by_id(user.id)

        assert updated.password_hash == "hash-2"
        assert updated.must_change_password is True

    asyncio.run(_with_db(run))


def test_user_repository_creates_and_deletes_sessions():
    async def run():
        users = UserCol(_Log())
        user = await users.create_user("trader", "hash-1", role="user")
        expires_at = datetime.now(UTC) + timedelta(hours=1)

        session = await users.create_session(user.id, "session-hash", expires_at)

        assert (await users.get_session("session-hash")).id == session.id
        assert await users.delete_session("session-hash") is True
        assert await users.get_session("session-hash") is None

    asyncio.run(_with_db(run))


def test_exchange_credential_repository_upserts_by_user_and_exchange():
    async def run():
        users = UserCol(_Log())
        user = await users.create_user("trader", "hash-1", role="user")
        credentials = ExchangeCredentialCol(_Log())

        first = await credentials.upsert_default(
            user.id,
            exchange="BINANCE",
            encrypted_api_key="encrypted-key-1",
            encrypted_api_secret="encrypted-secret-1",
            masked_api_key="abc***xyz",
        )
        second = await credentials.upsert_default(
            user.id,
            exchange="BINANCE",
            encrypted_api_key="encrypted-key-2",
            encrypted_api_secret="encrypted-secret-2",
            masked_api_key="def***xyz",
        )

        saved = await credentials.get_default(user.id, "BINANCE")

        assert first.id == second.id
        assert saved.encrypted_api_key == "encrypted-key-2"
        assert saved.masked_api_key == "def***xyz"

    asyncio.run(_with_db(run))


def test_strategy_config_repository_scopes_by_user():
    async def run():
        users = UserCol(_Log())
        first_user = await users.create_user("first", "hash-1", role="user")
        second_user = await users.create_user("second", "hash-2", role="user")
        strategies = StrategyConfigCol(_Log())

        created = await strategies.create(
            first_user.id,
            name="BTC live",
            strategy_name="macd_triple_divergence",
            symbol="BTC-USDT",
            interval="1m",
            params={"fast": 12},
        )
        await strategies.create(
            second_user.id,
            name="ETH live",
            strategy_name="macd_triple_divergence",
            symbol="ETH-USDT",
            interval="1m",
            params={},
        )

        assert [item.id for item in await strategies.list_by_user(first_user.id)] == [created.id]
        assert await strategies.get_for_user(created.id, second_user.id) is None

    asyncio.run(_with_db(run))
