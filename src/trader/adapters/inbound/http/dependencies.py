from __future__ import annotations

from fastapi import HTTPException, Request

from trader.auth.context import current_user
from trader.core.exchange.domain import MarginMode
from trader.core.exchange.exceptions import UserExchangeCredentialError
from trader.core.exchange.use_cases import RouteExchangeForTask, base_exchange_config


async def request_user_exchange(request: Request, *, margin_mode: MarginMode | None = None):
    rpc_app = getattr(request.app.state, "app", None)
    if rpc_app is None:
        raise HTTPException(status_code=503, detail="RPC application is not initialized")

    user = await current_user(request)
    if user is None or getattr(user, "is_admin", False):
        return getattr(rpc_app, "exchange", None)

    composition = getattr(request.app.state, "composition", None)
    cfg = getattr(request.app.state, "cfg", None)
    service_key = getattr(cfg, "secret_key", None)
    cipher_factory = getattr(composition, "secret_cipher_factory", None)
    exchange_factory = getattr(composition, "user_exchange_factory", None)
    db_manager = getattr(rpc_app, "db_manager", None)
    credential_repo = getattr(db_manager, "exchange_credential", None)
    base_cfg = base_exchange_config(getattr(rpc_app, "exchange", None), cfg)
    target_mode = margin_mode or base_cfg.margin_mode or MarginMode.SPOT
    logger = getattr(rpc_app, "logger", None)
    if not callable(exchange_factory):
        raise HTTPException(status_code=503, detail="exchange factory is not configured")

    route = RouteExchangeForTask(
        credential_repo,
        base_cfg=base_cfg,
        cipher=cipher_factory(service_key) if callable(cipher_factory) else None,
        exchange_factory=lambda exchange_cfg: exchange_factory(exchange_cfg, logger),
    )
    try:
        exchange = await route.execute(user.id, margin_mode=target_mode)
    except UserExchangeCredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if logger is not None and hasattr(logger, "info"):
        logger.info(
            "RPC selected user exchange "
            f"user_id={user.id} credential_id={exchange.credential_id} api_key={exchange.masked_api_key} "
            f"margin_mode={exchange.cfg.margin_mode.value}"
        )
    return exchange
