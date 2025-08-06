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
TRADER_DB_URI = "TRADER_DB_URI"
TRADER_DB_NAME = "TRADER_DB_NAME"
TRADER_WINDOW = "TRADER_WINDOW"
TRADER_TASKS = "TRADER_TASKS"
TRADER_CASH = "TRADER_CASH"
TRADER_STAT = "TRADER_STAT"
TRADER_NOTICE = "TRADER_NOTICE"
TRADER_API = "TRADER_API"


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
        db_uri=None,
        db_name=NAME,
        window=1000,
        tasks=None,
        cash=100000,
        stat=50,
        notice=None,
        api=None,
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
        self.db_uri = db_uri
        self.db_name = db_name
        self.window = window
        self.tasks = tasks
        self.cash = cash
        self.stat = stat
        self.notice = notice
        self.api = api

    def exportEnv(self):
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
        if self.db_uri:
            os.environ[TRADER_DB_URI] = self.db_uri
        os.environ[TRADER_DB_NAME] = self.db_name
        os.environ[TRADER_WINDOW] = str(self.window)
        if self.tasks:
            os.environ[TRADER_TASKS] = self.tasks
        os.environ[TRADER_CASH] = str(self.cash)
        os.environ[TRADER_STAT] = str(self.stat)
        os.environ[TRADER_NOTICE] = str(self.notice)
        os.environ[TRADER_API] = str(self.api)

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
            "db_uri": self.db_uri,
            "db_name": self.db_name,
            "window": self.window,
            "tasks": self.tasks,
            "cash": self.cash,
            "stat": self.stat,
            "notice": self.notice,
            "api": self.api,
        }

    def get_log_level(self) -> int:
        return logging.getLevelName(self.log_level)


def default() -> Config:
    return Config()
