from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from trader.auth.context import SESSION_COOKIE, SessionAuthMiddleware, require_admin
from trader.auth.sessions import create_session_token, hash_session_token
from trader.common.config import Config


class _UserRepo:
    def __init__(self, user):
        self.user = user
        self.session_hash = None

    async def get_session(self, session_hash):
        if session_hash == self.session_hash:
            return SimpleNamespace(user_id=self.user.id, expires_at=datetime.now(UTC) + timedelta(hours=1))
        return None

    async def get_by_id(self, user_id):
        if user_id == self.user.id:
            return self.user
        return None


def _app(user):
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware)
    repo = _UserRepo(user)
    app.state.cfg = Config(auth_username="admin", auth_password="marketBot2026")
    app.state.app = SimpleNamespace(db_manager=SimpleNamespace(user=repo))

    @app.get("/login")
    async def login():
        return {"page": "login"}

    @app.get("/change-password")
    async def change_password():
        return {"page": "change-password"}

    @app.get("/admin")
    async def admin():
        return {"page": "admin"}

    @app.get("/admin/users")
    async def admin_users(request: Request):
        await require_admin(request)
        return {"page": "admin-users"}

    return app, repo


def test_session_auth_redirects_unauthenticated_user_to_login():
    app, _repo = _app(SimpleNamespace(id=1, username="trader", role="user", status="active", must_change_password=False))
    client = TestClient(app)

    response = client.get("/admin", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_session_auth_allows_authenticated_user():
    token = create_session_token()
    app, repo = _app(SimpleNamespace(id=1, username="trader", role="user", status="active", must_change_password=False))
    repo.session_hash = hash_session_token(token)
    client = TestClient(app, cookies={SESSION_COOKIE: token})

    response = client.get("/admin")

    assert response.status_code == 200
    assert response.json() == {"page": "admin"}


def test_session_auth_forces_password_change():
    token = create_session_token()
    app, repo = _app(SimpleNamespace(id=1, username="trader", role="user", status="active", must_change_password=True))
    repo.session_hash = hash_session_token(token)
    client = TestClient(app, cookies={SESSION_COOKIE: token})

    response = client.get("/admin", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/change-password"


def test_require_admin_rejects_normal_user():
    token = create_session_token()
    app, repo = _app(SimpleNamespace(id=1, username="trader", role="user", status="active", must_change_password=False))
    repo.session_hash = hash_session_token(token)
    client = TestClient(app, cookies={SESSION_COOKIE: token})

    response = client.get("/admin/users")

    assert response.status_code == 403


def test_require_admin_allows_admin_user():
    token = create_session_token()
    app, repo = _app(SimpleNamespace(id=1, username="admin", role="admin", status="active", must_change_password=False))
    repo.session_hash = hash_session_token(token)
    client = TestClient(app, cookies={SESSION_COOKIE: token})

    response = client.get("/admin/users")

    assert response.status_code == 200
    assert response.json() == {"page": "admin-users"}
