from __future__ import annotations

from tortoise import Tortoise
from tortoise.exceptions import OperationalError

from trader.common.logger import Logger
from trader.database.availability import AvailabilityCol
from trader.database.config import build_tortoise_config, normalize_db_url
from trader.database.kline import DEFAULT_EXCHANGE, KlineCol
from trader.database.task import TaskCol


REQUIRED_TABLES = ("klines", "tasks", "availability")


class DatabaseSchemaError(RuntimeError):
    pass


class DatabaseManager:
    def __init__(self, cfg, log: Logger):
        self.log = log.log()
        self.cfg = cfg
        self.db_url = normalize_db_url(cfg.db)
        self.log.info("Init DatabaseManager")

        self.started = False
        self.task = None
        self.kline = None
        self.availability = None

    async def start(self):
        await Tortoise.init(config=build_tortoise_config(self.db_url))
        await self._ensure_schema_ready()
        exchange = self._default_exchange()
        self.kline = KlineCol(self.log, exchange=exchange)
        self.task = TaskCol(self.log)
        self.availability = AvailabilityCol(self.log)
        self.started = True

    async def stop(self):
        await Tortoise.close_connections()
        self.started = False

    def _default_exchange(self) -> str:
        if self.cfg.exchange:
            return "BINANCE"
        return DEFAULT_EXCHANGE

    async def _ensure_schema_ready(self) -> None:
        connection = Tortoise.get_connection("default")
        for table in REQUIRED_TABLES:
            try:
                await connection.execute_query(f'SELECT 1 FROM "{table}" LIMIT 1')
            except OperationalError as exc:
                message = str(exc)
                if "no such table" not in message.lower():
                    raise
                raise DatabaseSchemaError(
                    f"database schema is not initialized for {self.db_url}; missing table '{table}'. "
                    "Run `uv run trader-db migrate` before starting DB-backed workflows."
                ) from exc
