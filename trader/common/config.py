import logging
import os

from trader.common.common import NAME
from trader.utils.symbol_interval import SymbolInterval, Interval
from trader.utils.trend import TrendType, parseTrendType


class Config:
    def __init__(self,commission=0.001,
                      atr=True,
                      period=14,
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
                      notice=None):
        self.mode=parseTrendType(mode)
        self.commission=commission
        self.atr=atr
        self.period=period
        self.log_file=log_file
        self.plot=plot
        self.log_level=log_level
        self.exchange=exchange
        self.db_uri=db_uri
        self.db_name=db_name
        self.window=window
        self.tasks=tasks
        self.cash=cash
        self.stat=stat
        self.notice=notice

    def exportEnv(self):
        os.environ['commission'] = str(self.commission)
        os.environ['atr'] = str(self.atr)
        os.environ['period'] = str(self.period)
        os.environ['log_file'] = str(self.log_file)
        os.environ['plot'] = str(self.plot)
        os.environ['mode'] = self.mode.name
        os.environ['log_level'] = self.log_level

        if self.exchange:
            os.environ['exchange'] = self.exchange
        if self.db_uri:
            os.environ['db_uri'] = self.db_uri
        os.environ['db_name'] = self.db_name
        os.environ['window'] = str(self.window)
        if self.tasks:
            os.environ['tasks'] = self.tasks
        os.environ['cash'] = str(self.cash)
        os.environ['stat'] = str(self.stat)
        os.environ['notice'] = str(self.notice)

    def to_dict(self):
        return {
            'commission':self.commission,
            'atr':self.atr,
            'period':self.period,
            'log_file':self.log_file,
            'plot':self.plot,
            'mode':self.mode.name,
            'log_level':self.log_level,
            'exchange':self.exchange,
            'db_uri': self.db_uri,
            'db_name': self.db_name,
            'window': self.window,
            'tasks':self.tasks,
            'cash':self.cash,
            'stat':self.stat,
            'notice':self.notice
        }

    def get_log_level(self)->int:
        return logging.getLevelName(self.log_level)

def NewConfigFromEnv():
    commission = os.environ.get('commission')
    if commission is None:
        commission="0"
    period = os.environ.get('period')
    if period is None:
        period="0"
    window = os.environ.get('window')
    if window is None:
        window="0"

    return Config(
        float(commission),
        bool(os.environ.get('atr')),
        int(period),
        bool(os.environ.get('log_file')),
        bool(os.environ.get('plot')),
        os.environ.get('mode'),
        os.environ.get('log_level'),
        os.environ.get('exchange'),
        os.environ.get('db_uri'),
        os.environ.get('db_name'),
        int(window),
        os.environ.get('tasks'),
        os.environ.get('cash'),
        os.environ.get('stat'),
        os.environ.get('notice')
    )

def default()->Config:
    return Config()