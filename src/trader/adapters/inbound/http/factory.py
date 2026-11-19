from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi_auto_router import AutoRouter

from trader.adapters.inbound.http.auth import SESSION_COOKIE, AuthUser, SessionAuthMiddleware, auth_enabled, current_user, require_admin, require_user
from trader.adapters.inbound.http.exceptions import translate_domain_exception
from trader.adapters.inbound.http.queries import (
    get_accounts_info,
    get_klines_info,
    get_logs_info,
    get_taskinfo,
    open_orders_for_symbol_from_exchange,
)
from trader.adapters.inbound.http.schemas import AcctsInfo
from trader.core.exchange.domain import MarginMode
from trader.core.exchange.exceptions import UserExchangeCredentialError
from trader.core.exchange.use_cases import SymbolOpenOrders, base_exchange_config, build_user_exchange_context
from trader.core.identity.exceptions import AuthenticationError, PasswordPolicyError
from trader.core.identity.use_cases import (
    ChangePassword,
    EncryptUserCredential,
    LoginUser,
    LogoutUser,
    RegisterUser,
    ResetUserPassword,
)
from trader.core.shared.domain import NAME, Symbol


def list_strategy_options(composition: Any = None) -> list[str]:
    """Return the strategy catalog wired by the composition root."""
    provider = getattr(composition, "strategy_options", None)
    return list(provider()) if callable(provider) else []


def list_task_config_options() -> list[str]:
    root_dir = Path(__file__).resolve().parents[4]
    tasks_dir = root_dir / "configs" / "tasks"
    if not tasks_dir.is_dir():
        return []
    options = []
    for cfg_path in tasks_dir.rglob("*.json"):
        if cfg_path.is_file():
            options.append(cfg_path.relative_to(root_dir).as_posix())
    return sorted(options)


async def resolve_current_user(request: Request):
    composition = getattr(request.app.state, "composition", None)
    resolver = getattr(composition, "current_user_resolver", None)
    if callable(resolver):
        result = resolver(request)
        if inspect.isawaitable(result):
            return await result
        return result
    return await current_user(request)


async def _template_user(request: Request):
    user = await resolve_current_user(request)
    if user is not None:
        return user
    if not auth_enabled(request):
        return AuthUser(id=0, username="local-admin", role="admin", status="active", must_change_password=False)
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


def _default_binance_credential(credentials: list):
    for credential in credentials or []:
        if str(getattr(credential, "exchange", "") or "").upper() == "BINANCE":
            return credential
    return None


def create_app(
    composition: Any = None,
    *,
    lifespan: Any = None,
    static_dir: Path | None = None,
    templates_dir: Path | None = None,
    routers_dir: Path | None = None,
) -> FastAPI:
    """Create a FastAPI application wired strictly against injected composition/use cases."""
    cfg = getattr(composition, "cfg", None)
    version_fn = getattr(composition, "version", None)
    app_version = version_fn() if callable(version_fn) else str(version_fn or "0.0.0")

    fast_app = FastAPI(
        lifespan=lifespan,
        title="ChainerTrader",
        description="ChainerTrader",
        version=app_version,
    )
    fast_app.state.composition = composition
    fast_app.state.app = composition
    fast_app.state.cfg = cfg
    fast_app.state.live_event_bus = getattr(composition, "live_event_bus", None)

    if cfg is not None and callable(getattr(cfg, "is_auth_enabled", None)) and cfg.is_auth_enabled():
        fast_app.add_middleware(SessionAuthMiddleware)

    http_dir = Path(__file__).resolve().parent
    resolved_static = static_dir or (http_dir / "static")
    resolved_templates = templates_dir or (http_dir / "templates")
    resolved_routers = routers_dir or (http_dir / "routers")

    fast_app.mount("/static", StaticFiles(directory=str(resolved_static)), name="static")
    templates = Jinja2Templates(directory=str(resolved_templates))

    def _require_runtime(request: Request):
        runtime = getattr(request.app.state, "app", None) or getattr(request.app.state, "composition", None)
        if runtime is None:
            raise translate_domain_exception(RuntimeError("RPC application is not initialized"))
        return runtime

    def _require_user_repo(request: Request):
        runtime = _require_runtime(request)
        db_manager = getattr(runtime, "db_manager", None)
        if not db_manager or not getattr(db_manager, "user", None):
            from fastapi import HTTPException

            raise HTTPException(status_code=503, detail="user database is not initialized")
        return db_manager.user

    def _password_hasher(request: Request):
        runtime = _require_runtime(request)
        hasher = getattr(runtime, "password_hasher", None)
        if hasher is None:
            raise translate_domain_exception(RuntimeError("password hasher is not configured"))
        return hasher

    def _account_exchange_for_user(request: Request, runtime, user, credentials: list):
        factory = getattr(runtime, "user_exchange_factory", None)
        if not callable(factory):
            return getattr(runtime, "exchange", None)
        service_key = getattr(request.app.state.cfg, "secret_key", None)
        cipher_fn = getattr(runtime, "secret_cipher_factory", None)
        cipher = cipher_fn(service_key) if callable(cipher_fn) else None
        context = build_user_exchange_context(
            base_cfg=base_exchange_config(getattr(runtime, "exchange", None), request.app.state.cfg),
            credential=_default_binance_credential(credentials),
            user_id=user.id,
            margin_mode=MarginMode.CROSS_MARGIN,
            cipher=cipher,
        )
        return factory(context.cfg, getattr(runtime, "logger", None))

    def _user_accounts_info(request: Request, runtime, user, credentials: list) -> AcctsInfo:
        try:
            exchange = _account_exchange_for_user(request, runtime, user, credentials)
        except UserExchangeCredentialError as exc:
            return AcctsInfo(total=0, balances=[], account_error=str(exc))
        except Exception as exc:
            return AcctsInfo(total=0, balances=[], account_error=f"交易所账户读取失败: {exc}")
        account_app = SimpleNamespace(
            exchange=exchange,
            task_manager=getattr(runtime, "task_manager", None),
            logger=getattr(runtime, "logger", None),
        )
        return get_accounts_info(account_app, include_open_orders=False)

    @fast_app.get("/")
    async def read_root(request: Request):
        return templates.TemplateResponse(
            request,
            "index.html",
            {"version": app_version, "user": await resolve_current_user(request)},
        )

    @fast_app.get("/name")
    async def read_name():
        return {"name": NAME}

    @fast_app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": None, "registration_enabled": getattr(request.app.state.cfg, "registration_enabled", True)},
        )

    @fast_app.post("/login", response_class=HTMLResponse)
    async def login_submit(request: Request):
        users = _require_user_repo(request)
        form = await request.form()
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))
        try:
            result = await LoginUser(users, users, _password_hasher(request)).execute(
                username,
                password,
                session_ttl_hours=int(getattr(request.app.state.cfg, "session_ttl_hours", 24)),
            )
        except AuthenticationError:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "用户名或密码错误", "registration_enabled": getattr(request.app.state.cfg, "registration_enabled", True)},
                status_code=401,
            )

        target = "/change-password" if result.user.must_change_password else "/admin"
        response = RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            SESSION_COOKIE,
            result.session_token,
            httponly=True,
            samesite="lax",
            secure=bool(getattr(request.app.state.cfg, "session_cookie_secure", False)),
            expires=result.expires_at,
        )
        return response

    @fast_app.get("/register", response_class=HTMLResponse)
    async def register_page(request: Request):
        reg_enabled = bool(getattr(request.app.state.cfg, "registration_enabled", True))
        error = None if reg_enabled else "当前暂未开放用户注册"
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": error, "registration_enabled": reg_enabled},
        )

    @fast_app.post("/register", response_class=HTMLResponse)
    async def register_submit(request: Request):
        if not getattr(request.app.state.cfg, "registration_enabled", True):
            return templates.TemplateResponse(
                request,
                "register.html",
                {"error": "当前暂未开放用户注册", "registration_enabled": False},
                status_code=status.HTTP_403_FORBIDDEN,
            )
        users = _require_user_repo(request)
        form = await request.form()
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))
        try:
            await RegisterUser(users, _password_hasher(request)).execute(username, password)
        except PasswordPolicyError as exc:
            return templates.TemplateResponse(
                request,
                "register.html",
                {"error": str(exc), "registration_enabled": True},
                status_code=422,
            )
        except AuthenticationError:
            return templates.TemplateResponse(
                request,
                "register.html",
                {"error": "用户名已存在", "registration_enabled": True},
                status_code=409,
            )
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    @fast_app.get("/change-password", response_class=HTMLResponse)
    async def change_password_page(request: Request):
        return templates.TemplateResponse(
            request,
            "change_password.html",
            {"error": None, "user": await resolve_current_user(request)},
        )

    @fast_app.post("/change-password", response_class=HTMLResponse)
    async def change_password_submit(request: Request):
        user = await resolve_current_user(request)
        if user is None:
            return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        users = _require_user_repo(request)
        form = await request.form()
        password = str(form.get("password", ""))
        try:
            await ChangePassword(users, _password_hasher(request)).execute(user.id, user.username, password)
        except PasswordPolicyError as exc:
            return templates.TemplateResponse(request, "change_password.html", {"error": str(exc), "user": user}, status_code=422)
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

    @fast_app.post("/logout")
    async def logout(request: Request):
        users = _require_user_repo(request)
        await LogoutUser(users).execute(request.cookies.get(SESSION_COOKIE))
        response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @fast_app.get("/account", response_class=HTMLResponse)
    async def account_page(request: Request):
        user = await require_user(request)
        runtime = _require_runtime(request)
        credentials = []
        if runtime.db_manager and getattr(runtime.db_manager, "exchange_credential", None):
            credentials = await runtime.db_manager.exchange_credential.list_by_user(user.id)
        accts_info = _user_accounts_info(request, runtime, user, credentials)
        cancel_preview, cancel_preview_error = _account_cancel_preview(
            request, runtime, user, credentials, str(request.query_params.get("cancel_symbol", "") or "")
        )
        secret_key_ready_fn = getattr(runtime, "secret_key_ready_fn", None)
        secret_key_ready = bool(secret_key_ready_fn()) if callable(secret_key_ready_fn) else False
        return templates.TemplateResponse(
            request,
            "account.html",
            {
                "user": user,
                "credentials": credentials,
                "credential_error": None,
                "secret_key_ready": secret_key_ready,
                "accts_info": accts_info,
                "cancel_preview": cancel_preview,
                "cancel_preview_error": cancel_preview_error,
            },
        )

    def _account_cancel_preview(request: Request, runtime, user, credentials: list, raw_symbol: str):
        if not str(raw_symbol or "").strip():
            return None, ""
        symbol = _symbol_from_cancel_request(raw_symbol)
        if symbol is None:
            return None, "请输入完整交易对，例如 SOLUSDT。"
        try:
            exchange = _account_exchange_for_user(request, runtime, user, credentials)
            orders = open_orders_for_symbol_from_exchange(exchange, symbol)
        except Exception as exc:
            return None, f"{symbol.name()} 开放订单读取失败: {exc}"
        return {
            "symbol": symbol.name(),
            "orders": orders,
            "order_ids": ", ".join(str(order.get("order_id") or "").strip() for order in orders if order.get("order_id")),
            "count": len(orders),
        }, ""

    @fast_app.post("/account/exchange-credentials", response_class=HTMLResponse)
    async def account_exchange_credentials_submit(request: Request):
        user = await require_user(request)
        runtime = _require_runtime(request)
        service_key = getattr(request.app.state.cfg, "secret_key", None)
        cipher_fn = getattr(runtime, "secret_cipher_factory", None)
        cipher = cipher_fn(service_key) if callable(cipher_fn) else None
        if cipher is None:
            credentials = await runtime.db_manager.exchange_credential.list_by_user(user.id)
            return templates.TemplateResponse(
                request,
                "account.html",
                {
                    "user": user,
                    "credentials": credentials,
                    "credential_error": "TRADER_SECRET_KEY 未配置，不能保存交易所 API key。",
                    "secret_key_ready": False,
                    "accts_info": _user_accounts_info(request, runtime, user, credentials),
                },
                status_code=503,
            )
        form = await request.form()
        exchange_name = "BINANCE"
        api_key = str(form.get("api_key", "")).strip()
        api_secret = str(form.get("api_secret", "")).strip()
        validator = getattr(runtime, "credential_connectivity_validator", None)
        validation_error = validator(request.app.state.cfg, exchange_name, api_key, api_secret) if callable(validator) else None
        if validation_error is not None:
            credentials = await runtime.db_manager.exchange_credential.list_by_user(user.id)
            return templates.TemplateResponse(
                request,
                "account.html",
                {
                    "user": user,
                    "credentials": credentials,
                    "credential_error": validation_error,
                    "secret_key_ready": True,
                    "accts_info": _user_accounts_info(request, runtime, user, credentials),
                },
                status_code=400,
            )
        protected = EncryptUserCredential(cipher).execute(api_key, api_secret)
        await runtime.db_manager.exchange_credential.upsert_default(
            user.id,
            exchange=exchange_name,
            encrypted_api_key=protected.encrypted_api_key,
            encrypted_api_secret=protected.encrypted_api_secret,
            masked_api_key=protected.masked_api_key,
        )
        return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)

    @fast_app.post("/account/open-orders/cancel-cleanup-symbols")
    async def account_cancel_cleanup_symbol_open_orders(request: Request):
        user = await require_user(request)
        form = await request.form()
        requested_symbol = _symbol_from_cancel_request(str(form.get("symbol", "") or ""))
        if requested_symbol is None:
            raise translate_domain_exception(ValueError("必须指定要取消开放订单的交易对。"))
        runtime = _require_runtime(request)
        credentials = []
        if runtime.db_manager and getattr(runtime.db_manager, "exchange_credential", None):
            credentials = await runtime.db_manager.exchange_credential.list_by_user(user.id)
        exchange = _account_exchange_for_user(request, runtime, user, credentials)
        cancel_all = getattr(exchange, "cancel_all_open_orders", None)
        if callable(cancel_all):
            SymbolOpenOrders(exchange).cancel(requested_symbol)
        return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)

    @fast_app.get("/admin", response_class=HTMLResponse)
    async def admin_dashboard(request: Request):
        runtime = _require_runtime(request)
        user = await _template_user(request)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "tasks_info": await get_taskinfo(runtime, user),
                "version": app_version,
                "user": user,
            },
        )

    @fast_app.get("/admin/tasks", response_class=HTMLResponse)
    async def admin_tasks_page(request: Request):
        runtime = _require_runtime(request)
        user = await _template_user(request)
        raw_page = request.query_params.get("page", "1")
        try:
            page = max(1, int(raw_page))
        except ValueError:
            page = 1
        tasks_info = await get_taskinfo(runtime, user, page=page, per_page=20)
        return templates.TemplateResponse(
            request,
            "tasks.html",
            {
                "tasks_info": tasks_info,
                "user": user,
                "strategy_options": list_strategy_options(getattr(request.app.state, "composition", None)),
                "task_config_options": list_task_config_options(),
            },
        )

    @fast_app.get("/admin/klines", response_class=HTMLResponse)
    async def admin_klines_page(request: Request):
        runtime = _require_runtime(request)
        return templates.TemplateResponse(
            request,
            "klines.html",
            {"klines_info": await get_klines_info(runtime), "user": await _template_user(request)},
        )

    @fast_app.get("/admin/live", response_class=HTMLResponse)
    async def admin_live_page(request: Request):
        _require_runtime(request)
        return templates.TemplateResponse(request, "live.html", {"user": await _template_user(request)})

    @fast_app.get("/admin/logs", response_class=HTMLResponse)
    async def admin_logs_page(request: Request):
        runtime = _require_runtime(request)
        return templates.TemplateResponse(
            request,
            "logs.html",
            {"logs_info": get_logs_info(runtime), "user": await _template_user(request)},
        )

    @fast_app.get("/admin/users", response_class=HTMLResponse)
    async def admin_users_page(request: Request):
        await require_admin(request)
        users = await _require_user_repo(request).list_users()
        return templates.TemplateResponse(
            request,
            "admin_users.html",
            {"users": users, "user": await resolve_current_user(request), "temporary_password": None},
        )

    @fast_app.post("/admin/users/{user_id}/reset-password", response_class=HTMLResponse)
    async def admin_reset_user_password(request: Request, user_id: int):
        await require_admin(request)
        users_repo = _require_user_repo(request)
        try:
            temporary_password = await ResetUserPassword(users_repo, users_repo, _password_hasher(request)).execute(user_id)
        except AuthenticationError:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="user not found")
        users = await users_repo.list_users()
        return templates.TemplateResponse(
            request,
            "admin_users.html",
            {"users": users, "user": await resolve_current_user(request), "temporary_password": temporary_password},
        )

    @fast_app.get("/.well-known/appspecific/com.chrome.devtools.json")
    async def chrome_devtools_well_known():
        return Response(status_code=204)

    auto_router = AutoRouter(app=fast_app, routers_dir=str(resolved_routers), api_prefix="/api")
    auto_router.load_routers()

    return fast_app
