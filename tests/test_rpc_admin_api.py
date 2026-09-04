from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from trader.auth.context import SESSION_COOKIE, SessionAuthMiddleware
from trader.auth.sessions import create_session_token, hash_session_token
from trader.common.config import Config
from trader.rpc.api.admin import router


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

    async def list_users(self):
        return [self.user]


def _client_for(user):
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware)
    app.include_router(router, prefix="/api/admin")
    repo = _UserRepo(user)
    app.state.cfg = Config(auth_username="admin", auth_password="marketBot2026")
    app.state.app = SimpleNamespace(db_manager=SimpleNamespace(user=repo))
    token = create_session_token()
    repo.session_hash = hash_session_token(token)
    return TestClient(app, cookies={SESSION_COOKIE: token})


def test_admin_api_rejects_normal_user():
    client = _client_for(SimpleNamespace(id=1, username="trader", role="user", status="active", must_change_password=False))

    response = client.get("/api/admin/users")

    assert response.status_code == 403


def test_admin_api_lists_users_for_admin():
    client = _client_for(SimpleNamespace(id=1, username="admin", role="admin", status="active", must_change_password=False))

    response = client.get("/api/admin/users")

    assert response.status_code == 200
    assert response.json()["users"] == [{"id": 1, "username": "admin", "role": "admin", "status": "active"}]
