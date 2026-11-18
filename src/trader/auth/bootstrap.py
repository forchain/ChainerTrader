"""Edge wiring for administrator bootstrap; identity rules live in core."""

from __future__ import annotations

from trader.auth.credentials import FernetSecretCipher, service_key_available
from trader.core.identity.domain import User
from trader.core.identity.use_cases import EncryptUserCredential
from trader.exchange.exchange_config import parse_exchange_config


async def bootstrap_admin_exchange_credential(*, cfg, admin: User, credential_repo, log) -> bool:
    if admin.id is None or credential_repo is None or not getattr(cfg, "exchange", None):
        return False
    if await credential_repo.get_default(admin.id, "BINANCE") is not None:
        return False
    if not service_key_available(getattr(cfg, "secret_key", None)):
        log.warning("Skipping administrator exchange credential bootstrap: TRADER_SECRET_KEY is not configured")
        return False
    exchange_cfg = parse_exchange_config(cfg.exchange)
    if exchange_cfg is None or not exchange_cfg.api_key or not exchange_cfg.api_secret:
        return False
    protected = EncryptUserCredential(FernetSecretCipher(cfg.secret_key)).execute(exchange_cfg.api_key, exchange_cfg.api_secret)
    await credential_repo.upsert_default(
        admin.id,
        exchange="BINANCE",
        encrypted_api_key=protected.encrypted_api_key,
        encrypted_api_secret=protected.encrypted_api_secret,
        masked_api_key=protected.masked_api_key,
    )
    log.info("Bootstrapped administrator default exchange credential from configuration")
    return True
