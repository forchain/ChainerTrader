from trader.strategy.trader_result import TraderResult


class BackTraderStat:
    def __init__(self,strategy,
                 symbol_interval,
                 tret:TraderResult):
        self.strategy=strategy
        self.symbol_interval=symbol_interval
        self.tret=tret

class TraderStat:
    def __init__(self,strategy,
                 symbol_interval,
                 tret:TraderResult):
        self.strategy = strategy
        self.symbol_interval = symbol_interval
        self.tret = tret
