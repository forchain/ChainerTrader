from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from trader.rpc.app import app


class _UserRepo:
    def __init__(self):
        self.target = SimpleNamespace(
            id=2,
            username="trader",
            role="user",
            status="active",
            must_change_password=False,
            last_login_at=None,
        )
        self.deleted_sessions_for_user_id = None
        self.updated_password_user_id = None
        self.updated_password_must_change = None

    async def get_by_id(self, user_id):
        if user_id == self.target.id:
            return self.target
        return None

    async def update_password(self, user_id, _password_hash, *, must_change_password):
        self.updated_password_user_id = user_id
        self.updated_password_must_change = must_change_password
        self.target.must_change_password = must_change_password
        return True

    async def delete_sessions_for_user(self, user_id):
        self.deleted_sessions_for_user_id = user_id
        return 1

    async def list_users(self):
        return [self.target]


def test_admin_reset_user_password_deletes_target_sessions(monkeypatch):
    repo = _UserRepo()
    admin = SimpleNamespace(
        id=1,
        username="admin",
        role="admin",
        status="active",
        must_change_password=False,
        is_admin=True,
    )
    app.state.app = SimpleNamespace(db_manager=SimpleNamespace(user=repo))
    monkeypatch.setattr("trader.rpc.app.require_admin", AsyncMock(return_value=admin))
    monkeypatch.setattr("trader.rpc.app.current_user", AsyncMock(return_value=admin))

    response = TestClient(app).post("/admin/users/2/reset-password")

    assert response.status_code == 200
    assert repo.updated_password_user_id == 2
    assert repo.updated_password_must_change is True
    assert repo.deleted_sessions_for_user_id == 2
