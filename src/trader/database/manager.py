from __future__ import annotations

import inspect

from tortoise import Tortoise
from tortoise.exceptions import OperationalError

from trader.auth.passwords import hash_password, validate_password, validate_username
from trader.common.logger import Logger
from trader.database.availability import AvailabilityCol
from trader.database.config import build_tortoise_config, normalize_db_url
from trader.database.exchange_credential import ExchangeCredentialCol
from trader.database.execution_state import ExecutionStateCol
from trader.database.kline import DEFAULT_EXCHANGE, KlineCol
from trader.database.strategy_config import StrategyConfigCol
from trader.database.task import TaskCol
from trader.database.user import UserCol

REQUIRED_TABLES = ("klines", "tasks", "availability", "execution_states", "users", "sessions", "exchange_credentials", "strategy_configs")


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
        self.execution_state = None
        self.user = None
        self.exchange_credential = None
        self.strategy_config = None

    async def start(self):
        init_kwargs = {"config": build_tortoise_config(self.db_url)}
        if _supports_tortoise_global_fallback():
            init_kwargs["_enable_global_fallback"] = True
        await Tortoise.init(**init_kwargs)
        await self._ensure_schema_ready()
        exchange = self._default_exchange()
        self.kline = KlineCol(self.log, exchange=exchange)
        self.task = TaskCol(self.log)
        self.availability = AvailabilityCol(self.log)
        self.execution_state = ExecutionStateCol(self.log)
        self.user = UserCol(self.log)
        self.exchange_credential = ExchangeCredentialCol(self.log)
        self.strategy_config = StrategyConfigCol(self.log)
        await self._bootstrap_admin()
        self.started = True

    async def stop(self):
        await Tortoise.close_connections()
        self.started = False

    def _default_exchange(self) -> str:
        if self.cfg.exchange:
            return "BINANCE"
        return DEFAULT_EXCHANGE

    async def _bootstrap_admin(self) -> None:
        if not self.user or not getattr(self.cfg, "auth_username", None) or not getattr(self.cfg, "auth_password", None):
            return
        if await self.user.count_admins() > 0:
            return
        try:
            validate_username(self.cfg.auth_username)
            validate_password(self.cfg.auth_username, self.cfg.auth_password)
        except Exception as exc:
            raise DatabaseSchemaError(f"invalid bootstrap administrator credentials: {exc}") from exc
        await self.user.create_user(
            self.cfg.auth_username,
            hash_password(self.cfg.auth_password),
            role="admin",
        )
        self.log.info("Bootstrapped administrator account from configuration")

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


def _supports_tortoise_global_fallback() -> bool:
    parameters = inspect.signature(Tortoise.init).parameters
    return "_enable_global_fallback" in parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )
