from fastapi import FastAPI
from fastapi.testclient import TestClient

from trader.common.config import Config
from trader.rpc.auth import BasicAuthMiddleware


def _app():
    app = FastAPI()
    app.add_middleware(
        BasicAuthMiddleware,
        config=Config(
            auth_username="chainer",
            auth_password="secret",
            protected_paths=["/"],
        ),
    )

    @app.get("/")
    def index():
        return {"ok": True}

    return app


def test_basic_auth_middleware_skips_authentication_for_loopback_client():
    client = TestClient(_app(), client=("127.0.0.1", 50000))

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_basic_auth_middleware_keeps_authentication_for_non_local_client():
    client = TestClient(_app(), client=("192.168.1.20", 50000))

    response = client.get("/")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic realm=ChainerTrader"
