import asyncio

from tortoise import Tortoise

from trader.auth.credentials import decrypt_secret
from trader.common.config import Config
from trader.common.logger import Logger
from trader.database.config import build_tortoise_config
from trader.database.exchange_credential import ExchangeCredentialCol
from trader.database.manager import DatabaseManager
from trader.database.user import UserCol


async def _with_db(fn):
    await Tortoise.init(config=build_tortoise_config("sqlite://:memory:"))
    await Tortoise.generate_schemas()
    try:
        await fn()
    finally:
        await Tortoise.close_connections()


def _manager(cfg: Config) -> DatabaseManager:
    manager = DatabaseManager(cfg, Logger(cfg))
    manager.user = UserCol(manager.log)
    manager.exchange_credential = ExchangeCredentialCol(manager.log)
    return manager


def test_bootstrap_admin_seeds_default_exchange_credential_from_config():
    async def run():
        cfg = Config(
            auth_username="accept-admin",
            auth_password="AdminPass2026!",
            secret_key="service-secret",
            exchange='{"ty":"BINANCE","api_key":"admin-api-key","api_secret":"admin-api-secret"}',
        )
        manager = _manager(cfg)

        await manager._bootstrap_admin()

        admin = await manager.user.get_by_username("accept-admin")
        credential = await manager.exchange_credential.get_default(admin.id, "BINANCE")
        assert credential is not None
        assert decrypt_secret(cfg.secret_key, credential.encrypted_api_key) == "admin-api-key"
        assert decrypt_secret(cfg.secret_key, credential.encrypted_api_secret) == "admin-api-secret"
        assert credential.masked_api_key == "admi***-key"

    asyncio.run(_with_db(run))


def test_bootstrap_admin_does_not_overwrite_existing_default_exchange_credential():
    async def run():
        cfg = Config(
            auth_username="accept-admin",
            auth_password="AdminPass2026!",
            secret_key="service-secret",
            exchange='{"ty":"BINANCE","api_key":"config-api-key","api_secret":"config-api-secret"}',
        )
        manager = _manager(cfg)
        admin = await manager.user.create_user("existing-admin", "hash", role="admin")
        await manager.exchange_credential.upsert_default(
            admin.id,
            exchange="BINANCE",
            encrypted_api_key="encrypted-existing-key",
            encrypted_api_secret="encrypted-existing-secret",
            masked_api_key="exis***-key",
        )

        await manager._bootstrap_admin()

        credential = await manager.exchange_credential.get_default(admin.id, "BINANCE")
        assert credential.encrypted_api_key == "encrypted-existing-key"
        assert credential.encrypted_api_secret == "encrypted-existing-secret"
        assert credential.masked_api_key == "exis***-key"

    asyncio.run(_with_db(run))
