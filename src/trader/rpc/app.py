import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi_auto_router import AutoRouter

from trader.app.app import version
from trader.auth.context import SESSION_COOKIE, AuthUser, SessionAuthMiddleware, auth_enabled, current_user, require_admin, require_user
from trader.auth.credentials import encrypt_secret, mask_api_key, service_key_available
from trader.auth.passwords import (
    PasswordPolicyError,
    generate_temporary_password,
    hash_password,
    validate_password,
    validate_username,
    verify_password,
)
from trader.auth.sessions import create_session_token, hash_session_token
from trader.common import path
from trader.common.common import NAME
from trader.common.config import Config
from trader.exchange.binance.exchange import BinanceExchange
from trader.exchange.exchange_config import ExchangeConfig, MarginMode, parse_exchange_config
from trader.exchange.user_credentials import (
    UserExchangeCredentialError,
    attach_user_exchange_context,
    base_exchange_config,
    build_user_exchange_context,
)
from trader.live.monitor import GLOBAL_LIVE_EVENT_BUS
from trader.rpc.models import (
    AcctsInfo,
    get_accounts_info,
    get_klines_info,
    get_logs_info,
    get_taskinfo,
    open_orders_for_symbol_from_exchange,
)
from trader.rpc.rpc_app import RpcApp
from trader.utils.symbol_interval import Symbol


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = getattr(app.state, "cfg", None)
    if cfg is None:
        yield
        return

    rpc_app = RpcApp(cfg)
    app.state.app = rpc_app
    app.state.live_event_bus = GLOBAL_LIVE_EVENT_BUS

    await rpc_app.bootstrap_database_for_startup()
    await rpc_app.start_async()
    await rpc_app.wait_until_handler_ready()
    rpc_app.raise_main_task_error()
    yield
    await rpc_app.stop()


def get_directory(sub: str) -> str:
    baseDir = os.path.abspath(os.path.dirname(__file__))
    filePath = os.path.join(baseDir, sub)
    return os.path.realpath(filePath)


def _list_strategy_options() -> list[str]:
    strategy_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "strategy"))
    options: set[str] = set()
    ignore_py_files = {
        "__init__.py",
        "base_strategy.py",
        "backtrader_adapter.py",
        "execution_kernel.py",
        "lifecycle.py",
        "node.py",
        "risk.py",
        "signal_router.py",
        "strategy.py",
        "trader_result.py",
        "smoke_test.py",
    }
    if not os.path.isdir(strategy_dir):
        return []

    for name in os.listdir(strategy_dir):
        full_path = os.path.join(strategy_dir, name)
        if os.path.isfile(full_path) and name.endswith(".py") and name not in ignore_py_files:
            options.add(name[:-3])
            continue
        if os.path.isdir(full_path):
            nested = os.path.join(full_path, f"{name}.py")
            if os.path.isfile(nested):
                options.add(name)
    return sorted(options)


def _list_task_config_options() -> list[str]:
    root_dir = Path(__file__).resolve().parents[3]
    tasks_dir = root_dir / "configs" / "tasks"
    if not tasks_dir.is_dir():
        return []
    options = []
    for cfg_path in tasks_dir.rglob("*.json"):
        if cfg_path.is_file():
            relative = cfg_path.relative_to(root_dir).as_posix()
            options.append(relative)
    return sorted(options)


app = FastAPI(lifespan=lifespan, title="ChainerTrader", description="ChainerTrader", version=version())

app.mount("/static", StaticFiles(directory=get_directory("static")), name="static")

templates = Jinja2Templates(directory=get_directory("templates"))


async def _template_user(request: Request):
    user = await current_user(request)
    if user is not None:
        return user
    if not auth_enabled(request):
        # No-auth mode: keep admin pages navigable in local/dev and tests.
        return AuthUser(id=0, username="local-admin", role="admin", status="active", must_change_password=False)
    return None


def _require_rpc_app(request: Request) -> RpcApp:
    rpc_app = getattr(request.app.state, "app", None)
    if rpc_app is None:
        raise HTTPException(status_code=503, detail="RPC application is not initialized")
    return rpc_app


def start(cfg: Config):
    app_dir = os.path.join(path.GetTraderDir(), "rpc")

    bind_addr: str = "127.0.0.1:8000"
    if cfg.api:
        bind_addr = cfg.api

    # Parse bind address and port
    if ":" in bind_addr:
        host, port = bind_addr.rsplit(":", 1)
        if not host:  # Handle case like ":8000"
            host = "127.0.0.1"
        port = int(port)
    else:
        host = bind_addr
        port = 8000

    app.state.cfg = cfg

    # Add session authentication middleware if enabled.
    if cfg.is_auth_enabled():
        app.add_middleware(SessionAuthMiddleware)

    # Initialize and load routers
    routers_dir = os.path.abspath(os.path.dirname(__file__))
    routers_dir = os.path.join(routers_dir, "api")

    auto_router = AutoRouter(app=app, routers_dir=routers_dir, api_prefix="/api")  # relative to current file
    auto_router.load_routers()

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=False,
        app_dir=app_dir,
        log_level=cfg.get_log_level(),
    )


@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "version": version(),
            "user": await current_user(request),
        },
    )


@app.get("/name")
async def read_name():
    return {"name": NAME}


def _require_user_repo(request: Request):
    rpc_app = _require_rpc_app(request)
    if not rpc_app.db_manager or not getattr(rpc_app.db_manager, "user", None):
        raise HTTPException(status_code=503, detail="user database is not initialized")
    return rpc_app.db_manager.user


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request):
    users = _require_user_repo(request)
    form = await request.form()
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    user = await users.get_by_username(username)
    if user is None or user.status != "active" or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(request, "login.html", {"error": "用户名或密码错误"}, status_code=401)

    token = create_session_token()
    expires_at = datetime.now(UTC) + timedelta(hours=int(request.app.state.cfg.session_ttl_hours))
    await users.create_session(user.id, hash_session_token(token), expires_at)
    await users.mark_login(user.id, datetime.now(UTC))
    target = "/change-password" if user.must_change_password else "/admin"
    response = RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=bool(request.app.state.cfg.session_cookie_secure),
        expires=expires_at,
    )
    return response


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html", {"error": None})


@app.post("/register", response_class=HTMLResponse)
async def register_submit(request: Request):
    users = _require_user_repo(request)
    form = await request.form()
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    try:
        validate_username(username)
        validate_password(username, password)
    except PasswordPolicyError as exc:
        return templates.TemplateResponse(request, "register.html", {"error": str(exc)}, status_code=422)
    if await users.get_by_username(username) is not None:
        return templates.TemplateResponse(request, "register.html", {"error": "用户名已存在"}, status_code=409)
    await users.create_user(username, hash_password(password), role="user")
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request):
    return templates.TemplateResponse(request, "change_password.html", {"error": None, "user": await current_user(request)})


@app.post("/change-password", response_class=HTMLResponse)
async def change_password_submit(request: Request):
    user = await current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    users = _require_user_repo(request)
    form = await request.form()
    password = str(form.get("password", ""))
    try:
        validate_password(user.username, password)
    except PasswordPolicyError as exc:
        return templates.TemplateResponse(request, "change_password.html", {"error": str(exc), "user": user}, status_code=422)
    await users.update_password(user.id, hash_password(password), must_change_password=False)
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/logout")
async def logout(request: Request):
    users = _require_user_repo(request)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await users.delete_session(hash_session_token(token))
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/account", response_class=HTMLResponse)
async def account_page(request: Request):
    user = await require_user(request)
    rpc_app = _require_rpc_app(request)
    credentials = []
    if rpc_app.db_manager and getattr(rpc_app.db_manager, "exchange_credential", None):
        credentials = await rpc_app.db_manager.exchange_credential.list_by_user(user.id)
    accts_info = _user_accounts_info(request.app.state.cfg, rpc_app, user, credentials)
    cancel_preview, cancel_preview_error = _account_cancel_preview(
        request.app.state.cfg,
        rpc_app,
        user,
        credentials,
        str(request.query_params.get("cancel_symbol", "") or ""),
    )
    return templates.TemplateResponse(
        request,
        "account.html",
        {
            "user": user,
            "credentials": credentials,
            "credential_error": None,
            "secret_key_ready": service_key_available(getattr(request.app.state.cfg, "secret_key", None)),
            "accts_info": accts_info,
            "cancel_preview": cancel_preview,
            "cancel_preview_error": cancel_preview_error,
        },
    )


@app.post("/account/exchange-credentials", response_class=HTMLResponse)
async def account_exchange_credentials_submit(request: Request):
    user = await require_user(request)
    rpc_app = _require_rpc_app(request)
    logger = getattr(rpc_app, "logger", None)
    service_key = getattr(request.app.state.cfg, "secret_key", None)
    if not service_key_available(service_key):
        if logger is not None:
            logger.error(f"Exchange credential save rejected: user_id={user.id} detail=missing TRADER_SECRET_KEY")
        credentials = await rpc_app.db_manager.exchange_credential.list_by_user(user.id)
        return templates.TemplateResponse(
            request,
            "account.html",
            {
                "user": user,
                "credentials": credentials,
                "credential_error": "TRADER_SECRET_KEY 未配置，不能保存交易所 API key。",
                "secret_key_ready": False,
                "accts_info": _user_accounts_info(request.app.state.cfg, rpc_app, user, credentials),
            },
            status_code=503,
        )
    form = await request.form()
    exchange = "BINANCE"
    api_key = str(form.get("api_key", "")).strip()
    api_secret = str(form.get("api_secret", "")).strip()
    validation_error = _validate_exchange_credential_connectivity(request.app.state.cfg, exchange, api_key, api_secret)
    if validation_error is not None:
        if logger is not None:
            logger.error(
                f"Exchange credential validation failed: user_id={user.id} exchange={exchange} detail={validation_error}"
            )
        credentials = await rpc_app.db_manager.exchange_credential.list_by_user(user.id)
        return templates.TemplateResponse(
            request,
            "account.html",
            {
                "user": user,
                "credentials": credentials,
                "credential_error": validation_error,
                "secret_key_ready": True,
                "accts_info": _user_accounts_info(request.app.state.cfg, rpc_app, user, credentials),
            },
            status_code=400,
        )
    await rpc_app.db_manager.exchange_credential.upsert_default(
        user.id,
        exchange=exchange,
        encrypted_api_key=encrypt_secret(service_key, api_key),
        encrypted_api_secret=encrypt_secret(service_key, api_secret),
        masked_api_key=mask_api_key(api_key),
    )
    if logger is not None:
        logger.info(f"Exchange credential saved: user_id={user.id} exchange={exchange}")
    return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/account/open-orders/cancel-cleanup-symbols")
async def account_cancel_cleanup_symbol_open_orders(request: Request):
    user = await require_user(request)
    form = await request.form()
    requested_symbol = _symbol_from_cancel_request(str(form.get("symbol", "") or ""))
    if requested_symbol is None:
        raise HTTPException(status_code=400, detail="必须指定要取消开放订单的交易对。")
    rpc_app = _require_rpc_app(request)
    credentials = []
    if rpc_app.db_manager and getattr(rpc_app.db_manager, "exchange_credential", None):
        credentials = await rpc_app.db_manager.exchange_credential.list_by_user(user.id)
    exchange = _account_exchange_for_user(request.app.state.cfg, rpc_app, user, credentials)
    _cancel_requested_open_order_symbol(
        exchange,
        requested_symbol,
        getattr(rpc_app, "logger", None),
    )
    return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)


def _validate_exchange_credential_connectivity(cfg: Config, exchange: str, api_key: str, api_secret: str) -> str | None:
    if exchange != "BINANCE":
        return None
    try:
        base = parse_exchange_config(getattr(cfg, "exchange", "") or "") if getattr(cfg, "exchange", "") else ExchangeConfig()
        payload = base.model_dump()
        payload["api_key"] = api_key
        payload["api_secret"] = api_secret
        probe = BinanceExchange(ExchangeConfig(**payload))
        if not probe.ping():
            return "API key 连通性检查失败：无法连接交易所，请检查网络或密钥。"
    except Exception as exc:
        return f"API key 连通性检查失败：{exc}"
    return None


def _user_accounts_info(cfg: Config, rpc_app: RpcApp, user, credentials: list) -> AcctsInfo:
    try:
        exchange = _account_exchange_for_user(cfg, rpc_app, user, credentials)
    except UserExchangeCredentialError as exc:
        return AcctsInfo(total=0, balances=[], account_error=str(exc))
    except Exception as exc:
        logger = getattr(rpc_app, "logger", None)
        if logger is not None and hasattr(logger, "error"):
            logger.error(f"account page user exchange initialization failed: {exc}")
        return AcctsInfo(total=0, balances=[], account_error=f"交易所账户读取失败: {exc}")
    account_app = SimpleNamespace(
        exchange=exchange,
        task_manager=getattr(rpc_app, "task_manager", None),
        logger=getattr(rpc_app, "logger", None),
    )
    return get_accounts_info(account_app, include_open_orders=False)


def _account_exchange_for_user(cfg: Config, rpc_app: RpcApp, user, credentials: list):
    credential = _default_binance_credential(credentials)
    context = build_user_exchange_context(
        base_cfg=base_exchange_config(getattr(rpc_app, "exchange", None), cfg),
        service_key=getattr(cfg, "secret_key", None),
        credential=credential,
        user_id=user.id,
        margin_mode=MarginMode.CROSS_MARGIN,
    )
    logger = getattr(rpc_app, "logger", None)
    return attach_user_exchange_context(BinanceExchange(context.cfg, logger), context)


def _account_cancel_preview(cfg: Config, rpc_app: RpcApp, user, credentials: list, raw_symbol: str):
    if not str(raw_symbol or "").strip():
        return None, ""
    symbol = _symbol_from_cancel_request(raw_symbol)
    if symbol is None:
        return None, "请输入完整交易对，例如 SOLUSDT。"
    try:
        exchange = _account_exchange_for_user(cfg, rpc_app, user, credentials)
        orders = open_orders_for_symbol_from_exchange(exchange, symbol)
    except Exception as exc:
        logger = getattr(rpc_app, "logger", None)
        if logger is not None and hasattr(logger, "error"):
            logger.error(f"account cancel preview failed: symbol={symbol.name()} error={exc}")
        return None, f"{symbol.name()} 开放订单读取失败: {exc}"
    return {
        "symbol": symbol.name(),
        "orders": orders,
        "order_ids": ", ".join(str(order.get("order_id") or "").strip() for order in orders if order.get("order_id")),
        "count": len(orders),
    }, ""


def _default_binance_credential(credentials: list):
    for credential in credentials or []:
        if str(getattr(credential, "exchange", "") or "").upper() == "BINANCE":
            return credential
    return None


def _symbol_from_cancel_request(raw_symbol: str, quote_asset: str = "USDT") -> Symbol | None:
    normalized = str(raw_symbol or "").strip().upper().replace("/", "-").replace("_", "-")
    if not normalized:
        return None
    if "-" in normalized:
        symbol = Symbol(normalized)
        return symbol if not symbol.is_empty() else None

    compact = normalized.replace("-", "")
    quote_candidates = [quote_asset, "USDT", "USDC", "FDUSD", "BUSD", "BTC", "ETH", "BNB"]
    seen: set[str] = set()
    for quote in quote_candidates:
        quote = str(quote or "").strip().upper()
        if not quote or quote in seen:
            continue
        seen.add(quote)
        if compact.endswith(quote) and len(compact) > len(quote):
            return Symbol(f"{compact[:-len(quote)]}-{quote}")
    return None


def _cancel_requested_open_order_symbol(exchange, symbol: Symbol, logger=None) -> int:
    cancel_all = getattr(exchange, "cancel_all_open_orders", None)
    if not callable(cancel_all):
        return 0
    try:
        cancel_all(symbol)
        return 1
    except Exception as exc:
        if logger is not None and hasattr(logger, "error"):
            logger.error(f"account cancel_all_open_orders failed: symbol={symbol.name()} error={exc}")
        return 0


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    rpc_app = _require_rpc_app(request)
    user = await _template_user(request)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "tasks_info": await get_taskinfo(rpc_app, user),
            "version": rpc_app.version(),
            "user": user,
        },
    )


@app.get("/admin/tasks", response_class=HTMLResponse)
async def admin_tasks_page(request: Request):
    rpc_app = _require_rpc_app(request)
    user = await _template_user(request)
    raw_page = request.query_params.get("page", "1")
    try:
        page = max(1, int(raw_page))
    except ValueError:
        page = 1
    tasks_info = await get_taskinfo(rpc_app, user, page=page, per_page=20)
    return templates.TemplateResponse(
        request,
        "tasks.html",
        {
            "tasks_info": tasks_info,
            "user": user,
            "strategy_options": _list_strategy_options(),
            "task_config_options": _list_task_config_options(),
        },
    )


@app.get("/admin/klines", response_class=HTMLResponse)
async def admin_klines_page(request: Request):
    rpc_app = _require_rpc_app(request)
    return templates.TemplateResponse(request, "klines.html", {"klines_info": await get_klines_info(rpc_app), "user": await _template_user(request)})


@app.get("/admin/live", response_class=HTMLResponse)
async def admin_live_page(request: Request):
    _require_rpc_app(request)
    return templates.TemplateResponse(request, "live.html", {"user": await _template_user(request)})


@app.get("/admin/logs", response_class=HTMLResponse)
async def admin_logs_page(request: Request):
    rpc_app = _require_rpc_app(request)
    return templates.TemplateResponse(request, "logs.html", {"logs_info": get_logs_info(rpc_app), "user": await _template_user(request)})


@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    await require_admin(request)
    users = await _require_user_repo(request).list_users()
    return templates.TemplateResponse(request, "admin_users.html", {"users": users, "user": await current_user(request), "temporary_password": None})


@app.post("/admin/users/{user_id}/reset-password", response_class=HTMLResponse)
async def admin_reset_user_password(request: Request, user_id: int):
    await require_admin(request)
    users_repo = _require_user_repo(request)
    target = await users_repo.get_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    temporary_password = generate_temporary_password()
    await users_repo.update_password(user_id, hash_password(temporary_password), must_change_password=True)
    await users_repo.delete_sessions_for_user(user_id)
    users = await users_repo.list_users()
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {"users": users, "user": await current_user(request), "temporary_password": temporary_password},
    )


@app.get("/.well-known/appspecific/com.chrome.devtools.json")
async def chrome_devtools_well_known():
    return Response(status_code=204)
