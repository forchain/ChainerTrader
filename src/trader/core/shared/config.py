import logging
import math
import os
from typing import Any

from trader.core.shared.domain import NAME
from trader.core.strategy.domain.types import parseTrendType

DEFAULT_PERIOD = 14

TRADER_COMMISSION = "TRADER_COMMISSION"
TRADER_PERIOD = "TRADER_PERIOD"
TRADER_LOG_FILE = "TRADER_LOG_FILE"
TRADER_PLOT = "TRADER_PLOT"
TRADER_MODE = "TRADER_MODE"
TRADER_LOG_LEVEL = "TRADER_LOG_LEVEL"
TRADER_EXCHANGE = "TRADER_EXCHANGE"
TRADER_DB = "TRADER_DB"
TRADER_DB_NAME = "TRADER_DB_NAME"
TRADER_WINDOW = "TRADER_WINDOW"
TRADER_TASKS = "TRADER_TASKS"
TRADER_CASH = "TRADER_CASH"
TRADER_STAT = "TRADER_STAT"
TRADER_NOTICE = "TRADER_NOTICE"
TRADER_API = "TRADER_API"
TRADER_AUTH_USERNAME = "TRADER_AUTH_USERNAME"
TRADER_AUTH_PASSWORD = "TRADER_AUTH_PASSWORD"
TRADER_PROTECTED_PATHS = "TRADER_PROTECTED_PATHS"
TRADER_MIN_LIVE_TRADE_NOTIONAL = "TRADER_MIN_LIVE_TRADE_NOTIONAL"
TRADER_WARMUP_CANDLES = "TRADER_WARMUP_CANDLES"
TRADER_LIVE_ORDER_CLEANUP_SYMBOLS = "TRADER_LIVE_ORDER_CLEANUP_SYMBOLS"
TRADER_SECRET_KEY = "TRADER_SECRET_KEY"
TRADER_SESSION_COOKIE_SECURE = "TRADER_SESSION_COOKIE_SECURE"
TRADER_SESSION_TTL_HOURS = "TRADER_SESSION_TTL_HOURS"
TRADER_REGISTRATION_ENABLED = "TRADER_REGISTRATION_ENABLED"
TRADER_LEVERAGE_RATIO = "TRADER_LEVERAGE_RATIO"


def parse_log_file_config(value: Any) -> bool | str:
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip()
    if not raw:
        return False
    normalized = raw.lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off", "none", "null"}:
        return False
    return raw


def parse_bool_config(value: Any, default: bool = False, *, strict: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off", "none", "null", ""}:
        return False
    if strict:
        raise ValueError(f"invalid boolean configuration value: {value!r}")
    return default


def parse_string_list_config(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [item.strip().upper() for item in value.split(",") if item.strip()]
    return [str(item).strip().upper() for item in value if str(item).strip()]


def parse_leverage_ratio_config(value: Any, config_name: str = TRADER_LEVERAGE_RATIO) -> float:
    try:
        leverage_ratio = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{config_name} must be a finite float >= 1.0") from exc

    if not math.isfinite(leverage_ratio) or leverage_ratio < 1.0:
        raise ValueError(f"{config_name} must be a finite float >= 1.0")

    return leverage_ratio


class Config:
    def __init__(
        self,
        commission=0.001,
        period=DEFAULT_PERIOD,
        log_file=False,
        plot=False,
        mode=None,
        log_level="INFO",
        exchange=None,
        db=None,
        db_name=NAME,
        window=1000,
        tasks=None,
        cash: float = 100000.0,
        stat=50,
        notice=None,
        api=None,
        auth_username=None,
        auth_password=None,
        protected_paths=None,
        secret_key=None,
        session_cookie_secure: bool = False,
        session_ttl_hours: int = 24,
        leverage_ratio: float = 1.0,
        optimization_sample_timeout_seconds: float = 60.0,
        optimization_dataset_prepare_timeout_seconds: float = 600.0,
        optimization_dataset_download_request_budget: int = 20,
        optimization_no_progress_timeout_seconds: float = 180.0,
        optimization_max_failure_rate: float = 0.9,
        optimization_min_completed_samples_for_abort: int = 50,
        optimization_min_runnable_ratio: float = 0.1,
        optimization_parallelism_collapse_ratio: float = 0.25,
        optimization_worker_cpu_efficiency_threshold: float = 0.1,
        min_live_trade_notional: float = 11.0,
        warmup_candles: int = 500,
        live_order_cleanup_symbols=None,
        registration_enabled: bool = True,
        **kwargs,
    ):
        self.commission = commission
        self.period = period
        self.log_file = log_file
        self.plot = plot
        self.mode = parseTrendType(mode)
        self.log_level = log_level
        self.exchange = exchange
        self.db = db
        # Legacy MongoDB option retained for config compatibility; SQL database selection uses self.db.
        self.db_name = db_name
        self.window = window
        self.tasks = tasks
        self.cash = cash
        self.stat = stat
        self.notice = notice
        self.api = api
        self.auth_username = auth_username
        self.auth_password = auth_password
        self.protected_paths = protected_paths or []
        self.secret_key = secret_key
        self.session_cookie_secure = bool(session_cookie_secure)
        self.session_ttl_hours = int(session_ttl_hours)
        self.registration_enabled = parse_bool_config(registration_enabled, default=True, strict=True)
        self.leverage_ratio = parse_leverage_ratio_config(leverage_ratio)
        self.optimization_sample_timeout_seconds = optimization_sample_timeout_seconds
        self.optimization_dataset_prepare_timeout_seconds = optimization_dataset_prepare_timeout_seconds
        self.optimization_dataset_download_request_budget = optimization_dataset_download_request_budget
        self.optimization_no_progress_timeout_seconds = optimization_no_progress_timeout_seconds
        self.optimization_max_failure_rate = optimization_max_failure_rate
        self.optimization_min_completed_samples_for_abort = optimization_min_completed_samples_for_abort
        self.optimization_min_runnable_ratio = optimization_min_runnable_ratio
        self.optimization_parallelism_collapse_ratio = optimization_parallelism_collapse_ratio
        self.optimization_worker_cpu_efficiency_threshold = optimization_worker_cpu_efficiency_threshold
        self.min_live_trade_notional = float(min_live_trade_notional)
        self.warmup_candles = int(warmup_candles)
        self.live_order_cleanup_symbols = parse_string_list_config(live_order_cleanup_symbols)

    def export_env(self):
        os.environ[TRADER_COMMISSION] = str(self.commission)
        os.environ[TRADER_PERIOD] = str(self.period)
        os.environ[TRADER_LOG_FILE] = str(self.log_file)
        os.environ[TRADER_PLOT] = str(self.plot)
        os.environ[TRADER_MODE] = self.mode.name
        os.environ[TRADER_LOG_LEVEL] = self.log_level

        if self.exchange:
            os.environ[TRADER_EXCHANGE] = self.exchange
        if self.db:
            os.environ[TRADER_DB] = self.db
        os.environ[TRADER_DB_NAME] = self.db_name
        os.environ[TRADER_WINDOW] = str(self.window)
        if self.tasks:
            os.environ[TRADER_TASKS] = self.tasks
        os.environ[TRADER_CASH] = str(self.cash)
        os.environ[TRADER_STAT] = str(self.stat)
        os.environ[TRADER_NOTICE] = str(self.notice)
        os.environ[TRADER_API] = str(self.api)
        if self.auth_username:
            os.environ[TRADER_AUTH_USERNAME] = self.auth_username
        if self.auth_password:
            os.environ[TRADER_AUTH_PASSWORD] = self.auth_password
        if self.protected_paths:
            os.environ[TRADER_PROTECTED_PATHS] = ",".join(self.protected_paths)
        if self.secret_key:
            os.environ[TRADER_SECRET_KEY] = self.secret_key
        os.environ[TRADER_SESSION_COOKIE_SECURE] = str(self.session_cookie_secure)
        os.environ[TRADER_SESSION_TTL_HOURS] = str(self.session_ttl_hours)
        os.environ[TRADER_REGISTRATION_ENABLED] = str(self.registration_enabled)
        os.environ[TRADER_LEVERAGE_RATIO] = str(self.leverage_ratio)
        os.environ[TRADER_MIN_LIVE_TRADE_NOTIONAL] = str(self.min_live_trade_notional)
        os.environ[TRADER_WARMUP_CANDLES] = str(self.warmup_candles)
        if self.live_order_cleanup_symbols:
            os.environ[TRADER_LIVE_ORDER_CLEANUP_SYMBOLS] = ",".join(self.live_order_cleanup_symbols)

    def to_dict(self):
        return {
            "commission": self.commission,
            "period": self.period,
            "log_file": self.log_file,
            "plot": self.plot,
            "mode": self.mode.name,
            "log_level": self.log_level,
            "exchange": self.exchange,
            "db": self.db,
            "db_name": self.db_name,
            "window": self.window,
            "tasks": self.tasks,
            "cash": self.cash,
            "stat": self.stat,
            "notice": self.notice,
            "api": self.api,
            "auth_username": self.auth_username,
            "auth_password": self.auth_password,
            "protected_paths": self.protected_paths,
            "secret_key_configured": bool(self.secret_key),
            "session_cookie_secure": self.session_cookie_secure,
            "session_ttl_hours": self.session_ttl_hours,
            "registration_enabled": self.registration_enabled,
            "leverage_ratio": self.leverage_ratio,
            "optimization_sample_timeout_seconds": self.optimization_sample_timeout_seconds,
            "optimization_dataset_prepare_timeout_seconds": self.optimization_dataset_prepare_timeout_seconds,
            "optimization_dataset_download_request_budget": self.optimization_dataset_download_request_budget,
            "optimization_no_progress_timeout_seconds": self.optimization_no_progress_timeout_seconds,
            "optimization_max_failure_rate": self.optimization_max_failure_rate,
            "optimization_min_completed_samples_for_abort": self.optimization_min_completed_samples_for_abort,
            "optimization_min_runnable_ratio": self.optimization_min_runnable_ratio,
            "optimization_parallelism_collapse_ratio": self.optimization_parallelism_collapse_ratio,
            "optimization_worker_cpu_efficiency_threshold": self.optimization_worker_cpu_efficiency_threshold,
            "min_live_trade_notional": self.min_live_trade_notional,
            "warmup_candles": self.warmup_candles,
            "live_order_cleanup_symbols": self.live_order_cleanup_symbols,
        }

    def safe_to_dict(self):
        """Return configuration dictionary with sensitive information masked for logging"""
        safe_config = {
            "commission": self.commission,
            "period": self.period,
            "log_file": self.log_file,
            "plot": self.plot,
            "mode": self.mode.name,
            "log_level": self.log_level,
            "db_name": self.db_name,
            "window": self.window,
            "cash": self.cash,
            "stat": self.stat,
            "api": self.api,
            "protected_paths": self.protected_paths,
            "session_cookie_secure": self.session_cookie_secure,
            "session_ttl_hours": self.session_ttl_hours,
            "registration_enabled": self.registration_enabled,
            "leverage_ratio": self.leverage_ratio,
            "min_live_trade_notional": self.min_live_trade_notional,
            "warmup_candles": self.warmup_candles,
            "live_order_cleanup_symbols": self.live_order_cleanup_symbols,
        }

        # Mask sensitive fields
        if self.exchange:
            safe_config["exchange"] = "[MASKED]"
        if self.db:
            safe_config["db"] = "[MASKED]"
        if self.tasks:
            safe_config["tasks"] = "[MASKED]"
        if self.notice:
            safe_config["notice"] = "[MASKED]"
        if self.auth_username:
            safe_config["auth_username"] = "[MASKED]"
        if self.auth_password:
            safe_config["auth_password"] = "[MASKED]"
        if self.secret_key:
            safe_config["secret_key"] = "[MASKED]"

        return safe_config

    def get_log_level(self) -> int:
        return logging.getLevelName(self.log_level)

    def is_server(self) -> bool:
        return bool(self.api)

    def is_auth_enabled(self) -> bool:
        return self.auth_username is not None and self.auth_password is not None

    def is_protected_path(self, path: str) -> bool:
        """Check if a given path requires authentication based on protected path prefixes"""
        if not self.protected_paths:
            return False
        return any(path.startswith(protected_path) for protected_path in self.protected_paths)


def default() -> Config:
    return Config()
