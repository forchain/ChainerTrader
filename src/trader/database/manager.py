from __future__ import annotations

import inspect

from tortoise import Tortoise
from tortoise.exceptions import OperationalError

from trader.auth.credentials import encrypt_secret, mask_api_key, service_key_available
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
from trader.exchange.exchange_config import parse_exchange_config

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
            admin = await self.user.get_first_admin()
        else:
            try:
                validate_username(self.cfg.auth_username)
                validate_password(self.cfg.auth_username, self.cfg.auth_password)
            except Exception as exc:
                raise DatabaseSchemaError(f"invalid bootstrap administrator credentials: {exc}") from exc
            admin = await self.user.create_user(
                self.cfg.auth_username,
                hash_password(self.cfg.auth_password),
                role="admin",
            )
            self.log.info("Bootstrapped administrator account from configuration")
        if admin is not None:
            await self._bootstrap_admin_exchange_credential(admin.id)

    async def _bootstrap_admin_exchange_credential(self, admin_id: int) -> None:
        if not self.exchange_credential or not getattr(self.cfg, "exchange", None):
            return
        if await self.exchange_credential.get_default(admin_id, "BINANCE") is not None:
            return
        if not service_key_available(getattr(self.cfg, "secret_key", None)):
            self.log.warning("Skipping administrator exchange credential bootstrap: TRADER_SECRET_KEY is not configured")
            return
        exchange_cfg = parse_exchange_config(self.cfg.exchange)
        if exchange_cfg is None or not exchange_cfg.api_key or not exchange_cfg.api_secret:
            return
        await self.exchange_credential.upsert_default(
            admin_id,
            exchange="BINANCE",
            encrypted_api_key=encrypt_secret(self.cfg.secret_key, exchange_cfg.api_key),
            encrypted_api_secret=encrypt_secret(self.cfg.secret_key, exchange_cfg.api_secret),
            masked_api_key=mask_api_key(exchange_cfg.api_key),
        )
        self.log.info("Bootstrapped administrator default exchange credential from configuration")

    async def get_startup_admin(self):
        if not self.user:
            return None
        return await self.user.get_first_admin()

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
