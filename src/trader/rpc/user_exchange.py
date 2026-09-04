from __future__ import annotations

import inspect

from fastapi import HTTPException, Request

from trader.auth.context import current_user
from trader.exchange.binance import exchange as binance_exchange
from trader.exchange.exchange_config import MarginMode
from trader.exchange.user_credentials import (
    UserExchangeCredentialError,
    attach_user_exchange_context,
    base_exchange_config,
    build_user_exchange_context,
)


async def request_user_exchange(request: Request, *, margin_mode: MarginMode | None = None):
    rpc_app = getattr(request.app.state, "app", None)
    if rpc_app is None:
        raise HTTPException(status_code=503, detail="RPC application is not initialized")

    user = await current_user(request)
    if user is None or getattr(user, "is_admin", False):
        return getattr(rpc_app, "exchange", None)

    db_manager = getattr(rpc_app, "db_manager", None)
    credential_repo = getattr(db_manager, "exchange_credential", None)
    if credential_repo is None:
        raise HTTPException(status_code=400, detail="live trading requires a user exchange credential store")

    credential = credential_repo.get_default(user.id, "BINANCE")
    if inspect.isawaitable(credential):
        credential = await credential

    base_cfg = base_exchange_config(getattr(rpc_app, "exchange", None), getattr(request.app.state, "cfg", None))
    target_mode = margin_mode or base_cfg.margin_mode or MarginMode.SPOT
    try:
        context = build_user_exchange_context(
            base_cfg=base_cfg,
            service_key=getattr(getattr(request.app.state, "cfg", None), "secret_key", None),
            credential=credential,
            user_id=user.id,
            margin_mode=target_mode,
        )
    except UserExchangeCredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger = getattr(rpc_app, "logger", None)
    if logger is not None and hasattr(logger, "info"):
        logger.info(
            "RPC selected user exchange "
            f"user_id={user.id} credential_id={context.credential_id} api_key={context.masked_api_key} "
            f"margin_mode={context.cfg.margin_mode.value}"
        )
    return attach_user_exchange_context(binance_exchange.BinanceExchange(context.cfg, logger), context)
