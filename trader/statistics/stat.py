
class BackTraderStat:
    def __init__(self,strategy,
                 symbol_interval,
                 total_return_rate,
                 maxDrawdown,
                 maxDrawdownDuration,
                 volatility,
                 winRate,
                 plr,
                 avgProfit,
                 avgLoss):
        self.strategy=strategy
        self.symbol_interval=symbol_interval
        self.total_return_rate=total_return_rate
        self.maxDrawdown=maxDrawdown
        self.maxDrawdownDuration=maxDrawdownDuration
        self.volatility=volatility
        self.winRate=winRate
        self.plr=plr
        self.avgProfit=avgProfit
        self.avgLoss=avgLoss

class TraderStat:
    def __init__(self):
        pass
