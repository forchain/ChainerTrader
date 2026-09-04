from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trader.auth.credentials import decrypt_secret, mask_api_key, service_key_available
from trader.exchange.exchange_config import ExchangeConfig, MarginMode, parse_exchange_config


class UserExchangeCredentialError(RuntimeError):
    pass


@dataclass(frozen=True)
class UserExchangeContext:
    cfg: ExchangeConfig
    user_id: int
    credential_id: int | None
    masked_api_key: str


def base_exchange_config(exchange: Any = None, cfg: Any = None) -> ExchangeConfig:
    exchange_cfg = getattr(exchange, "cfg", None)
    if isinstance(exchange_cfg, ExchangeConfig):
        return exchange_cfg
    raw_exchange_cfg = getattr(cfg, "exchange", "") if cfg is not None else ""
    if raw_exchange_cfg:
        parsed = parse_exchange_config(raw_exchange_cfg)
        if parsed is not None:
            return parsed
    return ExchangeConfig()


def build_user_exchange_context(
    *,
    base_cfg: ExchangeConfig | None,
    service_key: str | None,
    credential: Any,
    user_id: int,
    margin_mode: MarginMode,
) -> UserExchangeContext:
    if credential is None:
        raise UserExchangeCredentialError(f"missing BINANCE API credential for user_id={user_id}")
    if not service_key_available(service_key):
        raise UserExchangeCredentialError("TRADER_SECRET_KEY is required to read user-owned Binance credentials")

    api_key = decrypt_secret(service_key, credential.encrypted_api_key)
    api_secret = decrypt_secret(service_key, credential.encrypted_api_secret)
    payload = (base_cfg or ExchangeConfig()).model_dump()
    payload["api_key"] = api_key
    payload["api_secret"] = api_secret
    payload["margin_mode"] = margin_mode
    return UserExchangeContext(
        cfg=ExchangeConfig(**payload),
        user_id=user_id,
        credential_id=getattr(credential, "id", None),
        masked_api_key=str(getattr(credential, "masked_api_key", "") or mask_api_key(api_key)),
    )


def attach_user_exchange_context(exchange: Any, context: UserExchangeContext) -> Any:
    setattr(exchange, "user_id", context.user_id)
    setattr(exchange, "credential_id", context.credential_id)
    setattr(exchange, "masked_api_key", context.masked_api_key)
    return exchange
