import logging
import os
from argparse import Namespace
from typing import Any

from trader.common.common import NAME
from trader.utils.trend import parseTrendType

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
        optimization_sample_timeout_seconds: float = 60.0,
        optimization_dataset_prepare_timeout_seconds: float = 600.0,
        optimization_dataset_download_request_budget: int = 20,
        optimization_no_progress_timeout_seconds: float = 180.0,
        optimization_max_failure_rate: float = 0.9,
        optimization_min_completed_samples_for_abort: int = 50,
        optimization_min_runnable_ratio: float = 0.1,
        optimization_parallelism_collapse_ratio: float = 0.25,
        optimization_worker_cpu_efficiency_threshold: float = 0.1,
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
        self.optimization_sample_timeout_seconds = optimization_sample_timeout_seconds
        self.optimization_dataset_prepare_timeout_seconds = optimization_dataset_prepare_timeout_seconds
        self.optimization_dataset_download_request_budget = optimization_dataset_download_request_budget
        self.optimization_no_progress_timeout_seconds = optimization_no_progress_timeout_seconds
        self.optimization_max_failure_rate = optimization_max_failure_rate
        self.optimization_min_completed_samples_for_abort = optimization_min_completed_samples_for_abort
        self.optimization_min_runnable_ratio = optimization_min_runnable_ratio
        self.optimization_parallelism_collapse_ratio = optimization_parallelism_collapse_ratio
        self.optimization_worker_cpu_efficiency_threshold = optimization_worker_cpu_efficiency_threshold

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
            "optimization_sample_timeout_seconds": self.optimization_sample_timeout_seconds,
            "optimization_dataset_prepare_timeout_seconds": self.optimization_dataset_prepare_timeout_seconds,
            "optimization_dataset_download_request_budget": self.optimization_dataset_download_request_budget,
            "optimization_no_progress_timeout_seconds": self.optimization_no_progress_timeout_seconds,
            "optimization_max_failure_rate": self.optimization_max_failure_rate,
            "optimization_min_completed_samples_for_abort": self.optimization_min_completed_samples_for_abort,
            "optimization_min_runnable_ratio": self.optimization_min_runnable_ratio,
            "optimization_parallelism_collapse_ratio": self.optimization_parallelism_collapse_ratio,
            "optimization_worker_cpu_efficiency_threshold": self.optimization_worker_cpu_efficiency_threshold,
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


def new_and_env(cli: Namespace | None = None) -> Config:
    """Build Config: built-in defaults, then environment variables, then explicit CLI flags (highest)."""

    commission = 0.001
    period = DEFAULT_PERIOD
    log_file = False
    plot = False
    mode = None
    log_level = "INFO"
    exchange = None
    db = None
    db_name = NAME
    window = 1000
    tasks = None
    cash = 100000.0
    stat = 50
    notice = None
    api = None
    auth_username = None
    auth_password = None
    protected_paths: list[str] = []

    commission = float(os.environ.get(TRADER_COMMISSION, commission))
    period = int(os.environ.get(TRADER_PERIOD, period))
    log_file = parse_log_file_config(os.environ.get(TRADER_LOG_FILE, log_file))
    plot = os.environ.get(TRADER_PLOT, str(plot)).lower() == "true"
    mode = os.environ.get(TRADER_MODE, mode)
    log_level = os.environ.get(TRADER_LOG_LEVEL, log_level)
    exchange = os.environ.get(TRADER_EXCHANGE, exchange)
    db = os.environ.get(TRADER_DB, db)
    db_name = os.environ.get(TRADER_DB_NAME, db_name)
    window = int(os.environ.get(TRADER_WINDOW, window))
    tasks = os.environ.get(TRADER_TASKS, tasks)
    cash = float(os.environ.get(TRADER_CASH, cash))
    stat = int(os.environ.get(TRADER_STAT, stat))
    notice = os.environ.get(TRADER_NOTICE, notice)
    api = os.environ.get(TRADER_API, api)
    auth_username = os.environ.get(TRADER_AUTH_USERNAME, auth_username)
    auth_password = os.environ.get(TRADER_AUTH_PASSWORD, auth_password)

    protected_paths_env = os.environ.get(TRADER_PROTECTED_PATHS, "")
    if protected_paths_env:
        protected_paths = [path.strip() for path in protected_paths_env.split(",") if path.strip()]

    if cli is not None:
        a: dict[str, Any] = vars(cli)
        if "commission" in a:
            commission = float(a["commission"])
        if "period" in a:
            period = int(a["period"])
        if "log_file" in a:
            log_file = bool(a["log_file"])
        if "plot" in a:
            plot = bool(a["plot"])
        if "mode" in a:
            mode = a["mode"]
        if "log_level" in a:
            log_level = a["log_level"]
        if "exchange" in a:
            exchange = a["exchange"]
        if "db" in a:
            db = a["db"]
        if "db_name" in a:
            db_name = a["db_name"]
        if "window" in a:
            window = int(a["window"])
        if "tasks" in a:
            tasks = a["tasks"]
        if "cash" in a:
            cash = float(a["cash"])
        if "stat" in a:
            stat = int(a["stat"])
        if "notice" in a:
            notice = a["notice"]
        if "api" in a:
            api = a["api"]
        if "auth_username" in a:
            auth_username = a["auth_username"]
        if "auth_password" in a:
            auth_password = a["auth_password"]
        if "protected_paths" in a:
            raw_pp = a["protected_paths"]
            protected_paths = [p.strip() for p in raw_pp.split(",") if p.strip()] if raw_pp else []

    return Config(
        commission=commission,
        period=period,
        log_file=log_file,
        plot=plot,
        mode=mode,
        log_level=log_level,
        exchange=exchange,
        db=db,
        db_name=db_name,
        window=window,
        tasks=tasks,
        cash=cash,
        stat=stat,
        notice=notice,
        api=api,
        auth_username=auth_username,
        auth_password=auth_password,
        protected_paths=protected_paths,
    )
