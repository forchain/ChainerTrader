import asyncio

from tortoise import Tortoise

from trader.adapters.outbound.persistence.exchange_credential_repository import (
    TortoiseExchangeCredentialRepository,
)
from trader.core.exchange.interfaces import ExchangeCredentialRepository
from trader.database.config import build_tortoise_config


async def _with_db(fn):
    await Tortoise.init(config=build_tortoise_config("sqlite://:memory:"))
    await Tortoise.generate_schemas()
    try:
        await fn()
    finally:
        await Tortoise.close_connections()


def test_repository_implements_exchange_credential_port():
    assert isinstance(TortoiseExchangeCredentialRepository(), ExchangeCredentialRepository)


def test_repository_round_trips_encrypted_credentials_per_user():
    async def run():
        repo = TortoiseExchangeCredentialRepository()

        created = await repo.upsert_default(
            7,
            exchange="BINANCE",
            encrypted_api_key="encrypted-key",
            encrypted_api_secret="encrypted-secret",
            masked_api_key="abcd***3456",
        )
        assert created.user_id == 7
        assert created.exchange == "BINANCE"
        assert created.encrypted_api_key == "encrypted-key"
        assert created.encrypted_api_secret == "encrypted-secret"
        assert created.masked_api_key == "abcd***3456"

        updated = await repo.upsert_default(
            7,
            exchange="BINANCE",
            encrypted_api_key="rotated-key",
            encrypted_api_secret="rotated-secret",
            masked_api_key="wxyz***7890",
        )
        assert updated.id == created.id

        stored = await repo.get_default(7, "BINANCE")
        assert stored.encrypted_api_key == "rotated-key"
        assert stored.masked_api_key == "wxyz***7890"
        assert [item.id for item in await repo.list_by_user(7)] == [created.id]

        assert await repo.get_default(8, "BINANCE") is None
        assert await repo.delete_for_user(created.id, 8) is False
        assert await repo.delete_for_user(created.id, 7) is True
        assert await repo.get_default(7, "BINANCE") is None

    asyncio.run(_with_db(run))
