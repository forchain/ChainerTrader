import os

from trader.strategy.strategy import parseStrategyType
from trader.utils.trend import TrendType, parseTrendType


class Config:
    def __init__(self,strategy_type=None,commission=0.001,atr=True,period=14,log_file=False,plot=False,mode=None,log_level="INFO",exchange=None,symbols=None,data_file=None,db_uri=None):
        self.strategy=parseStrategyType(strategy_type)
        self.mode=parseTrendType(mode)
        self.commission=commission
        self.atr=atr
        self.period=period
        self.log_file=log_file
        self.plot=plot
        self.log_level=log_level
        self.exchange=exchange
        self.symbols=symbols
        self.data_file=data_file
        self.db_uri=db_uri

    def exportEnv(self):
        if self.strategy:
            os.environ['strategy_type'] = self.strategy.name

        os.environ['commission'] = str(self.commission)
        os.environ['atr'] = str(self.atr)
        os.environ['period'] = str(self.period)
        os.environ['log_file'] = str(self.log_file)
        os.environ['plot'] = str(self.plot)
        os.environ['mode'] = self.mode.name
        os.environ['log_level'] = self.log_level

        if self.exchange:
            os.environ['exchange'] = self.exchange
        if self.symbols:
            os.environ['symbols'] = self.symbols
        if self.data_file:
            os.environ['data_file'] = self.data_file
        if self.db_uri:
            os.environ['db_uri'] = self.db_uri

    def to_dict(self):
        strategy_type = None
        if self.strategy:
            strategy_type=self.strategy.name

        return {
            "strategy_type":strategy_type,
            'commission':self.commission,
            'atr':self.atr,
            'period':self.period,
            'log_file':self.log_file,
            'plot':self.plot,
            'mode':self.mode.name,
            'log_level':self.log_level,
            'exchange':self.exchange,
            'symbols':self.symbols,
            'data_file':self.data_file,
            'db_uri': self.db_uri,
        }

    def symbols_list(self):
        if self.symbols:
            return self.symbols.split(',')
        return None

def NewConfigFromEnv():
    commission = os.environ.get('commission')
    if commission is None:
        commission="0"
    period = os.environ.get('period')
    if period is None:
        period="0"

    return Config(
        os.environ.get('strategy_type'),
        float(commission),
        bool(os.environ.get('atr')),
        int(period),
        bool(os.environ.get('log_file')),
        bool(os.environ.get('plot')),
        os.environ.get('mode'),
        os.environ.get('log_level'),
        os.environ.get('exchange'),
        os.environ.get('symbols'),
        os.environ.get('data_file'),
        os.environ.get('db_uri'),
    )