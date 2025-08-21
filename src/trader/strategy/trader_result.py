from typing import Any

from trader.utils.operate import Operate


class TraderResult:
    def __init__(
        self,
        total_return_rate,
        max_drawdown,
        max_drawdown_duration,
        volatility,
        win_rate,
        plr,
        avg_profit,
        avg_loss,
        buys,
        sells,
        operate: Operate,
        hold_rate,
        data_len: int,
    ):
        self.total_return_rate = total_return_rate
        self.max_drawdown = max_drawdown
        self.max_drawdown_duration = max_drawdown_duration
        self.volatility = volatility
        self.win_rate = win_rate
        self.plr = plr
        self.avg_profit = avg_profit
        self.avg_loss = avg_loss
        self.buys = buys
        self.sells = sells
        self.operate = operate
        self.hold_rate = hold_rate
        self.data_len = data_len

    def to_dict(self) -> dict[str, Any]:
        ret = {
            "total_return_rate": self.total_return_rate,
            "max_drawdown": self.max_drawdown,
            "max_drawdown_duration": f"{self.max_drawdown_duration}",
            "volatility": self.volatility,
            "win_rate": self.win_rate,
            "plr": self.plr,
            "avg_profit": self.avg_profit,
            "avg_loss": self.avg_loss,
            "buys": self.buys,
            "sells": self.sells,
            "hold_rate": self.hold_rate,
            "data_len": self.data_len,
        }
        if self.operate:
            ret["operate"] = self.operate.to_dict()

        return ret
