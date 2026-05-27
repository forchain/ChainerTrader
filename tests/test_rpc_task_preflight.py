import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from trader.auth.context import SessionAuthMiddleware
from trader.common.config import Config
from trader.rpc.api.tasks import router
from trader.task.task_config import TaskConfig
from trader.task.task_manager import TaskManager
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import Interval, SymbolInterval


class _UserRepo:
    async def get_session(self, _session_hash):
        return None


class _CredentialRepo:
    async def get_default(self, _user_id, _exchange):
        return None


class _TaskManager:
    def __init__(self, states=None):
        self._states = states or []

    async def get_all_task_state(self, user_id=None):
        return list(self._states)


class _Logger:
    def __init__(self):
        self.errors = []
        self.infos = []

    def error(self, message):
        self.errors.append(message)

    def info(self, message):
        self.infos.append(message)


def test_user_owned_live_task_requires_saved_exchange_credential():
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware)
    app.include_router(router, prefix="/api/tasks")
    app.state.cfg = Config(auth_username="admin", auth_password="AdminPass123", secret_key="service-secret")
    logger = _Logger()
    app.state.app = SimpleNamespace(
        db_manager=SimpleNamespace(user=_UserRepo(), exchange_credential=_CredentialRepo()),
        send_add_tasks_msg=lambda *_args, **_kwargs: {"result": "should-not-start"},
        logger=logger,
    )

    @app.middleware("http")
    async def inject_user(request, call_next):
        request.state.user = SimpleNamespace(id=5, username="alice", role="user", status="active", must_change_password=False, is_admin=False)
        return await call_next(request)

    client = TestClient(app)
    response = client.post(
        "/api/tasks",
        content='[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1h","strategy":"macd_triple_divergence"}]',
    )

    assert response.status_code == 400
    assert "missing BINANCE API credential" in response.json()["detail"]
    assert "user_id=5" in logger.errors[0]
    assert "missing BINANCE API credential" in logger.errors[0]


def test_user_owned_manual_notify_live_task_does_not_require_saved_exchange_credential():
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware)
    app.include_router(router, prefix="/api/tasks")
    send_add_tasks_msg = Mock(return_value={"result": "success"})
    app.state.cfg = Config(auth_username="admin", auth_password="AdminPass123", secret_key="service-secret")
    app.state.app = SimpleNamespace(
        db_manager=SimpleNamespace(user=_UserRepo(), exchange_credential=_CredentialRepo()),
        task_manager=_TaskManager([]),
        send_add_tasks_msg=send_add_tasks_msg,
        logger=_Logger(),
    )

    @app.middleware("http")
    async def inject_user(request, call_next):
        request.state.user = SimpleNamespace(id=5, username="alice", role="user", status="active", must_change_password=False, is_admin=False)
        return await call_next(request)

    client = TestClient(app)
    response = client.post(
        "/api/tasks",
        content=(
            '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m",'
            '"strategy":"macd_triple_divergence","live_execution_mode":"manual_notify"}]'
        ),
    )

    assert response.status_code == 400
    assert "missing BINANCE API credential" in response.json()["detail"]
    assert send_add_tasks_msg.call_count == 0


def test_task_manager_uses_default_exchange_for_user_owned_manual_notify_task():
    manager = TaskManager(Config(tasks="[]"), SimpleNamespace(info=lambda *_args, **_kwargs: None), SimpleNamespace(), "default-exchange")
    cfg = TaskConfig(
        1,
        TaskType.TRADER,
        SymbolInterval("BTC-USDT", Interval("1m")),
        strategies=["macd_triple_divergence"],
        live_execution_mode="manual_notify",
        user_id=5,
    )

    assert asyncio.run(manager._exchange_for_task(cfg)) == "default-exchange"


def test_task_creation_requires_authenticated_user():
    app = FastAPI()
    app.include_router(router, prefix="/api/tasks")
    send_add_tasks_msg = Mock(return_value={"result": "should-not-start"})
    app.state.app = SimpleNamespace(send_add_tasks_msg=send_add_tasks_msg, logger=_Logger())

    client = TestClient(app)
    response = client.post("/api/tasks", content='[{"task_type":"DEBUG","limit":1}]')

    assert response.status_code == 401
    assert send_add_tasks_msg.call_count == 0


def test_user_owned_live_task_requires_service_key():
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware)
    app.include_router(router, prefix="/api/tasks")
    app.state.cfg = Config(auth_username="admin", auth_password="AdminPass123")
    app.state.app = SimpleNamespace(
        db_manager=SimpleNamespace(user=_UserRepo(), exchange_credential=_CredentialRepo()),
        send_add_tasks_msg=lambda *_args, **_kwargs: {"result": "should-not-start"},
        logger=_Logger(),
    )

    @app.middleware("http")
    async def inject_user(request, call_next):
        request.state.user = SimpleNamespace(id=5, username="alice", role="user", status="active", must_change_password=False, is_admin=False)
        return await call_next(request)

    client = TestClient(app)
    response = client.post(
        "/api/tasks",
        content='[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1h","strategy":"macd_triple_divergence"}]',
    )

    assert response.status_code == 400
    assert "TRADER_SECRET_KEY" in response.json()["detail"]


def test_task_creation_rejected_when_user_has_running_task():
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware)
    app.include_router(router, prefix="/api/tasks")
    send_add_tasks_msg = Mock(return_value={"result": "should-not-start"})
    running = SimpleNamespace(state=SimpleNamespace(name="RUNNING"))
    app.state.cfg = Config(auth_username="admin", auth_password="AdminPass123")
    app.state.app = SimpleNamespace(
        db_manager=SimpleNamespace(user=_UserRepo()),
        task_manager=_TaskManager([running]),
        send_add_tasks_msg=send_add_tasks_msg,
        logger=_Logger(),
    )

    @app.middleware("http")
    async def inject_user(request, call_next):
        request.state.user = SimpleNamespace(id=5, username="alice", role="user", status="active", must_change_password=False, is_admin=False)
        return await call_next(request)

    client = TestClient(app)
    response = client.post("/api/tasks", content='[{"task_type":"DEBUG","limit":1}]')

    assert response.status_code == 409
    assert "already has a running task" in response.json()["detail"]
    assert send_add_tasks_msg.call_count == 0


def test_task_creation_allowed_when_only_other_user_has_running_task():
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware)
    app.include_router(router, prefix="/api/tasks")
    send_add_tasks_msg = Mock(return_value={"result": "success"})
    app.state.cfg = Config(auth_username="admin", auth_password="AdminPass123")
    app.state.app = SimpleNamespace(
        db_manager=SimpleNamespace(user=_UserRepo()),
        task_manager=_TaskManager([]),
        send_add_tasks_msg=send_add_tasks_msg,
        logger=_Logger(),
    )

    @app.middleware("http")
    async def inject_user(request, call_next):
        request.state.user = SimpleNamespace(id=5, username="alice", role="user", status="active", must_change_password=False, is_admin=False)
        return await call_next(request)

    client = TestClient(app)
    response = client.post("/api/tasks", content='[{"task_type":"DEBUG","limit":1}]')

    assert response.status_code == 200
    assert send_add_tasks_msg.call_count == 1


def test_task_creation_from_config_path_attaches_current_user_id():
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware)
    app.include_router(router, prefix="/api/tasks")
    send_add_tasks_msg = Mock(return_value={"result": "success"})
    app.state.cfg = Config(auth_username="admin", auth_password="AdminPass123", secret_key="service-secret")
    logger = _Logger()
    class _CredentialOkRepo:
        async def get_default(self, _user_id, _exchange):
            return SimpleNamespace(encrypted_api_key="k", encrypted_api_secret="s")

    app.state.app = SimpleNamespace(
        db_manager=SimpleNamespace(user=_UserRepo(), exchange_credential=_CredentialOkRepo()),
        task_manager=_TaskManager([]),
        send_add_tasks_msg=send_add_tasks_msg,
        logger=logger,
    )

    @app.middleware("http")
    async def inject_user(request, call_next):
        request.state.user = SimpleNamespace(id=5, username="alice", role="user", status="active", must_change_password=False, is_admin=False)
        return await call_next(request)

    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setattr("trader.rpc.api.tasks._user_exchange_ping_ok", lambda *_args, **_kwargs: True)
    try:
        client = TestClient(app)
        response = client.post("/api/tasks", content="configs/tasks/live/manual_notify_btc_1m.json")

        assert response.status_code == 200
        send_add_tasks_msg.assert_called_once_with("configs/tasks/live/manual_notify_btc_1m.json", user_id=5)
        assert "user_id=5" in logger.infos[0]
        assert "source=configs/tasks/live/manual_notify_btc_1m.json" in logger.infos[0]
    finally:
        monkeypatch.undo()


def test_task_creation_returns_clear_error_for_invalid_config_payload():
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware)
    app.include_router(router, prefix="/api/tasks")
    send_add_tasks_msg = Mock(return_value={"result": "should-not-start"})
    logger = _Logger()
    app.state.cfg = Config(auth_username="admin", auth_password="AdminPass123")
    app.state.app = SimpleNamespace(
        db_manager=SimpleNamespace(user=_UserRepo()),
        task_manager=_TaskManager([]),
        send_add_tasks_msg=send_add_tasks_msg,
        logger=logger,
    )

    @app.middleware("http")
    async def inject_user(request, call_next):
        request.state.user = SimpleNamespace(id=5, username="alice", role="user", status="active", must_change_password=False, is_admin=False)
        return await call_next(request)

    client = TestClient(app)
    response = client.post("/api/tasks", content="configs/tasks/live/missing.json")

    assert response.status_code == 400
    assert "task config file not found: configs/tasks/live/missing.json" in response.json()["detail"]
    assert "source=configs/tasks/live/missing.json" in logger.errors[0]
    assert send_add_tasks_msg.call_count == 0


def test_task_config_template_api_returns_configs_task_file_content():
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware)
    app.include_router(router, prefix="/api/tasks")
    app.state.cfg = Config(auth_username="admin", auth_password="AdminPass123")
    app.state.app = SimpleNamespace(db_manager=SimpleNamespace(user=_UserRepo()))

    @app.middleware("http")
    async def inject_user(request, call_next):
        request.state.user = SimpleNamespace(id=5, username="alice", role="user", status="active", must_change_password=False, is_admin=False)
        return await call_next(request)

    client = TestClient(app)
    response = client.get("/api/tasks/config-template", params={"path": "configs/tasks/live/manual_notify_btc_1m.json"})

    assert response.status_code == 200
    assert response.json()["path"] == "configs/tasks/live/manual_notify_btc_1m.json"
    assert '"task_type": "TRADER"' in response.json()["content"]


def test_task_config_template_api_rejects_paths_outside_configs_tasks():
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware)
    app.include_router(router, prefix="/api/tasks")
    app.state.cfg = Config(auth_username="admin", auth_password="AdminPass123")
    app.state.app = SimpleNamespace(db_manager=SimpleNamespace(user=_UserRepo()))

    @app.middleware("http")
    async def inject_user(request, call_next):
        request.state.user = SimpleNamespace(id=5, username="alice", role="user", status="active", must_change_password=False, is_admin=False)
        return await call_next(request)

    client = TestClient(app)
    response = client.get("/api/tasks/config-template", params={"path": "../example.env"})

    assert response.status_code == 400
