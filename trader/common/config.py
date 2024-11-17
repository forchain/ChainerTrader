import os

from trader.strategy.strategy import parseStrategyType
from trader.utils.trend import TrendType, parseTrendType


class Config:
    def __init__(self,strategy_type=None,commission=0.001,atr=True,period=14,log_file=False,plot=False,mode=None):
        self.strategy=parseStrategyType(strategy_type)
        self.mode=parseTrendType(mode)
        self.commission=commission
        self.atr=atr
        self.period=period
        self.log_file=log_file
        self.plot=plot

    def exportEnv(self):
        if self.strategy:
            os.environ['strategy_type'] = self.strategy.name

        os.environ['commission'] = str(self.commission)
        os.environ['atr'] = str(self.atr)
        os.environ['period'] = str(self.period)
        os.environ['log_file'] = str(self.log_file)
        os.environ['plot'] = str(self.plot)
        os.environ['mode'] = self.mode.name

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
    )