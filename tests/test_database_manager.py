import pytest
from tortoise import Tortoise

from trader.common.config import Config
from trader.common.logger import Logger
from trader.database.manager import DatabaseManager, DatabaseSchemaError, _supports_tortoise_global_fallback


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_database_manager_reports_missing_schema_with_migration_hint(tmp_path):
    db_path = tmp_path / "missing-schema.db"
    manager = DatabaseManager(Config(db=f"sqlite://{db_path}"), Logger(Config()))

    try:
        with pytest.raises(DatabaseSchemaError) as exc_info:
            await manager.start()
    finally:
        await Tortoise.close_connections()

    message = str(exc_info.value)
    assert "missing table 'klines'" in message
    assert "uv run trader-db migrate" in message


@pytest.mark.anyio
async def test_database_manager_enables_tortoise_global_fallback(monkeypatch):
    calls = []
    manager = DatabaseManager(Config(db="sqlite://:memory:"), Logger(Config()))

    async def fake_init(*args, **kwargs):
        calls.append(kwargs)

    async def fake_schema_ready():
        return None

    monkeypatch.setattr("trader.database.manager.Tortoise.init", fake_init)
    monkeypatch.setattr(manager, "_ensure_schema_ready", fake_schema_ready)

    await manager.start()

    assert calls
    assert calls[0]["_enable_global_fallback"] is True


def test_detects_tortoise_global_fallback_support(monkeypatch):
    async def fake_init(config=None, _enable_global_fallback=False):
        return None

    monkeypatch.setattr("trader.database.manager.Tortoise.init", fake_init)

    assert _supports_tortoise_global_fallback() is True
