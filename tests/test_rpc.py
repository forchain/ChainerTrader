import os

from fastapi.testclient import TestClient

from trader.app.app import NAME
from trader.rpc.rpc import rpc

client = TestClient(rpc)


def test_read_name():
    response = client.get("/name")
    assert response.status_code == 200
    assert response.json() == {"name": NAME}