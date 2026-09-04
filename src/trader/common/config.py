import logging
import os

from trader.common.common import NAME
from trader.utils.trend import parseTrendType

DEFAULT_PERIOD = 14

TRADER_COMMISSION = "TRADER_COMMISSION"
TRADER_ATR = "TRADER_ATR"
TRADER_STOPLOSS = "TRADER_STOPLOSS"
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


class Config:
    def __init__(
        self,
        commission=0.001,
        atr=True,
        stoploss=False,
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
    ):
        self.commission = commission
        self.atr = atr
        self.stoploss = stoploss
        self.period = period
        self.log_file = log_file
        self.plot = plot
        self.mode = parseTrendType(mode)
        self.log_level = log_level
        self.exchange = exchange
        self.db = db
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

    def export_env(self):
        os.environ[TRADER_COMMISSION] = str(self.commission)
        os.environ[TRADER_ATR] = str(self.atr)
        os.environ[TRADER_STOPLOSS] = str(self.stoploss)
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
            "atr": self.atr,
            "stoploss": self.stoploss,
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
        }

    def safe_to_dict(self):
        """Return configuration dictionary with sensitive information masked for logging"""
        safe_config = {
            "commission": self.commission,
            "atr": self.atr,
            "stoploss": self.stoploss,
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
        return self.api is not None

    def is_auth_enabled(self) -> bool:
        return self.auth_username is not None and self.auth_password is not None

    def is_protected_path(self, path: str) -> bool:
        """Check if a given path requires authentication based on protected path prefixes"""
        if not self.protected_paths:
            return False
        return any(path.startswith(protected_path) for protected_path in self.protected_paths)


def default() -> Config:
    return Config()


def new_and_env(
    commission=0.001,
    atr=True,
    stoploss=False,
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
    cash=100000,
    stat=50,
    notice=None,
    api=None,
    auth_username=None,
    auth_password=None,
    protected_paths=None,
) -> Config:

    commission = float(os.environ.get(TRADER_COMMISSION, commission))
    atr = os.environ.get(TRADER_ATR, str(atr)).lower() == "true"
    stoploss = os.environ.get(TRADER_STOPLOSS, str(stoploss)).lower() == "true"
    period = int(os.environ.get(TRADER_PERIOD, period))
    log_file = os.environ.get(TRADER_LOG_FILE, str(log_file)).lower() == "true"
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

    # Parse protected paths from environment variable (comma-separated)
    protected_paths_env = os.environ.get(TRADER_PROTECTED_PATHS, "")
    if protected_paths_env:
        protected_paths = [path.strip() for path in protected_paths_env.split(",") if path.strip()]
    else:
        protected_paths = protected_paths or []

    return Config(
        commission=commission,
        atr=atr,
        stoploss=stoploss,
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
