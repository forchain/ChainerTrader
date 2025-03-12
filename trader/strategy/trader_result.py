from fastapi.openapi.models import Operation


class TraderResult:
    def __init__(self,total_return_rate,max_drawdown,max_drawdown_duration,volatility,win_rate,plr,avg_profit,avg_loss,buys,sells,operate:Operation,hold_rate):
        self.total_return_rate=total_return_rate
        self.max_drawdown=max_drawdown
        self.max_drawdown_duration=max_drawdown_duration
        self.volatility=volatility
        self.win_rate=win_rate
        self.plr=plr
        self.avg_profit=avg_profit
        self.avg_loss=avg_loss
        self.buys=buys
        self.sells=sells
        self.operate=operate
        self.hold_rate=hold_rate