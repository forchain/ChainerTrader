import pytest
from tortoise import Tortoise

from trader.common.config import Config
from trader.common.logger import Logger
from trader.database.manager import DatabaseManager, DatabaseSchemaError


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
