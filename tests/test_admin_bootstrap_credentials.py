import asyncio

from tests.persistence_harness import initialized_database
from trader.adapters.outbound.identity.argon2_hasher import Argon2PasswordHasher
from trader.adapters.outbound.identity.fernet_cipher import FernetSecretCipher, decrypt_secret, service_key_available
from trader.adapters.outbound.logging.logger import Logger
from trader.adapters.outbound.persistence.exchange_credential import ExchangeCredentialCol
from trader.adapters.outbound.persistence.manager import DatabaseManager
from trader.adapters.outbound.persistence.user import UserCol
from trader.core.identity.use_cases import BootstrapAdministrator, bootstrap_admin_exchange_credential
from trader.core.shared.config import Config


async def _with_db(fn):
    async with initialized_database():
        await fn()


def _manager(cfg: Config) -> DatabaseManager:
    manager = DatabaseManager(cfg, Logger(cfg))
    manager.user = UserCol(manager.log)
    manager.exchange_credential = ExchangeCredentialCol(manager.log)
    return manager


async def _bootstrap(cfg: Config, manager: DatabaseManager) -> None:
    admin = await BootstrapAdministrator(manager.user, Argon2PasswordHasher()).execute(cfg.auth_username, cfg.auth_password)
    await bootstrap_admin_exchange_credential(
        cfg=cfg,
        admin=admin,
        credential_repo=manager.exchange_credential,
        log=manager.log,
        cipher_factory=lambda key: FernetSecretCipher(key) if service_key_available(key) else None,
    )


def test_bootstrap_admin_seeds_default_exchange_credential_from_config():
    async def run():
        cfg = Config(
            auth_username="accept-admin",
            auth_password="AdminPass2026!",
            secret_key="service-secret",
            exchange='{"ty":"BINANCE","api_key":"admin-api-key","api_secret":"admin-api-secret"}',
        )
        manager = _manager(cfg)

        await _bootstrap(cfg, manager)

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

        await _bootstrap(cfg, manager)

        credential = await manager.exchange_credential.get_default(admin.id, "BINANCE")
        assert credential.encrypted_api_key == "encrypted-existing-key"
        assert credential.encrypted_api_secret == "encrypted-existing-secret"
        assert credential.masked_api_key == "exis***-key"

    asyncio.run(_with_db(run))
