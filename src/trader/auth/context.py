from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from starlette.responses import RedirectResponse

from trader.auth.sessions import hash_session_token, is_expired

SESSION_COOKIE = "chainer_session"
PUBLIC_PATHS = (
    "/login",
    "/register",
    "/static",
    "/name",
    "/api/health",
    "/.well-known",
)


@dataclass(frozen=True)
class AuthUser:
    id: int
    username: str
    role: str
    status: str
    must_change_password: bool

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def is_public_path(path: str) -> bool:
    return path == "/" or any(path.startswith(public_path) for public_path in PUBLIC_PATHS)


def auth_enabled(request: Request) -> bool:
    cfg = getattr(request.app.state, "cfg", None)
    rpc_app = getattr(request.app.state, "app", None)
    db_manager = getattr(rpc_app, "db_manager", None)
    return bool(cfg and cfg.is_auth_enabled() and db_manager and getattr(db_manager, "user", None))


async def current_user(request: Request) -> AuthUser | None:
    if not auth_enabled(request):
        return None
    cached = getattr(request.state, "user", None)
    if cached is not None:
        return cached

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    user_repo = request.app.state.app.db_manager.user
    session = await user_repo.get_session(hash_session_token(token))
    if session is None or is_expired(session.expires_at):
        return None
    user = await user_repo.get_by_id(session.user_id)
    if user is None or user.status != "active":
        return None
    auth_user = AuthUser(
        id=user.id,
        username=user.username,
        role=user.role,
        status=user.status,
        must_change_password=bool(user.must_change_password),
    )
    request.state.user = auth_user
    return auth_user


async def require_user(request: Request) -> AuthUser:
    user = await current_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    return user


async def require_admin(request: Request) -> AuthUser:
    user = await require_user(request)
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="administrator required")
    return user


class SessionAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        if not auth_enabled(request) or is_public_path(request.url.path):
            await self.app(scope, receive, send)
            return

        user = await current_user(request)
        if user is None:
            response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
            await response(scope, receive, send)
            return

        if user.must_change_password and not request.url.path.startswith("/change-password") and not request.url.path.startswith("/api/auth/logout"):
            response = RedirectResponse(url="/change-password", status_code=status.HTTP_303_SEE_OTHER)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
