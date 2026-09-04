from datetime import timedelta
from typing import Any

from trader.utils.operate import Operate, parse_opts


class TraderResult:
    def __init__(
        self,
        total_return_rate,
        max_drawdown,
        max_drawdown_duration: timedelta,
        volatility,
        win_rate,
        plr,
        avg_profit,
        avg_loss,
        buys,
        sells,
        opts: list[Operate],
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
        self.opts = opts
        self.hold_rate = hold_rate
        self.data_len = data_len

    def to_dict(self) -> dict[str, Any]:
        ret = {
            "total_return_rate": self.total_return_rate,
            "max_drawdown": self.max_drawdown,
            "max_drawdown_duration": self.max_drawdown_duration.total_seconds(),
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
        if not self.opts:
            opts = []
            for opt in self.opts:
                opts.append(opt.to_dict())
            ret["opts"] = opts

        return ret


def parse_trader_result(data) -> TraderResult:
    # Helper function to safely convert numeric values
    def safe_float(value, default=0.0):
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except (ValueError, TypeError):
                return default
        return default

    def safe_int(value, default=0):
        if value is None:
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, (float, str)):
            try:
                return int(float(value))
            except (ValueError, TypeError):
                return default
        return default

    # Handle max_drawdown_duration conversion safely
    max_drawdown_duration = safe_float(data.get("max_drawdown_duration", 0.0))

    tr = TraderResult(
        safe_float(data.get("total_return_rate", 0.0)),
        safe_float(data.get("max_drawdown", 0.0)),
        timedelta(seconds=max_drawdown_duration),
        safe_float(data.get("volatility", 0.0)),
        safe_float(data.get("win_rate", 0.0)),
        safe_float(data.get("plr", 0.0)),
        safe_float(data.get("avg_profit", 0.0)),
        safe_float(data.get("avg_loss", 0.0)),
        safe_int(data.get("buys", 0)),
        safe_int(data.get("sells", 0)),
        parse_opts(data.get("opts", "")),  # operate field
        safe_float(data.get("hold_rate", 0.0)),
        safe_int(data.get("data_len", 0)),
    )

    return tr
