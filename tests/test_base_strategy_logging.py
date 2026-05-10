import datetime as dt

import backtrader as bt
import pandas as pd

from trader.strategy.base_strategy import BaseStrategy


class RecordingLog:
    def __init__(self):
        self.infos = []

    def info(self, msg, *_args, **_kwargs):
        self.infos.append(msg)

    def debug(self, *_args, **_kwargs):
        pass


class InitLoggingStrategy(BaseStrategy):
    def __init__(self):
        super().__init__()
        self.log_info("init marker")


def test_strategy_init_log_uses_not_started_instead_of_epoch_zero():
    log = RecordingLog()
    df = pd.DataFrame(
        [
            {"datetime": dt.datetime(2025, 1, 27, 0, 0), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
        ]
    )
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.PandasData(dataname=df, datetime="datetime"))
    cerebro.addstrategy(InitLoggingStrategy, log=log)

    cerebro.run()

    init_logs = [msg for msg in log.infos if "init marker" in msg]
    assert init_logs
    assert "[not_started]" in init_logs[0]
    assert "1970-01-01" not in init_logs[0]
