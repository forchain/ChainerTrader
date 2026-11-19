"""Golden numeric snapshot captured before the indicator kernels moved into core."""

import hashlib
import json
import math

import backtrader as bt
import numpy as np
import pandas as pd

from trader.adapters.outbound.backtrader.indicators.chainerrsi import ChainerRSIHisto
from trader.adapters.outbound.backtrader.indicators.kdj import KDJIndicator
from trader.adapters.outbound.backtrader.indicators.pivot_high import PivotHigh
from trader.adapters.outbound.backtrader.indicators.pivot_low import PivotLow
from trader.adapters.outbound.backtrader.indicators.qqe import QQECalc
from trader.adapters.outbound.backtrader.indicators.qqe_mod import QQEMod
from trader.adapters.outbound.backtrader.indicators.rsrs import RSRSIndicator
from trader.adapters.outbound.backtrader.indicators.super_trend import SuperTrend
from trader.adapters.outbound.backtrader.indicators.trend_a import TrendA
from trader.core.strategy.domain.types import MAType

GOLDEN_SHA256 = "889a3f00d1bbcd0ecf829019afee439cdf1f839470cbd883b568ad2546f8d4ca"


def _dataframe(periods=320):
    rng = np.random.RandomState(20240101)
    close = 20000.0 + np.cumsum(rng.normal(0.0, 25.0, periods))
    open_ = np.concatenate(([close[0]], close[:-1]))
    high = np.maximum(open_, close) + rng.uniform(1.0, 40.0, periods)
    low = np.minimum(open_, close) - rng.uniform(1.0, 40.0, periods)
    volume = 1000.0 + np.arange(periods, dtype=float)
    index = pd.date_range(start="2024-01-01", periods=periods, freq="h")
    return pd.DataFrame(dict(datetime=index, open=open_, high=high, low=low, close=close, volume=volume))


def _line_values(line, length):
    out = []
    for value in line.get(size=length):
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = math.nan
        out.append(None if math.isnan(number) else number)
    return out


class _IndicatorCapture(bt.Strategy):
    def __init__(self):
        self.pivot_high = PivotHigh(self.data.high, left=3, right=3)
        self.pivot_low = PivotLow(self.data.low, left=3, right=3)
        self.super_trend = SuperTrend(self.data, periods=10, multiplier=3.0, change_atr=True)
        self.qqe_mod = QQEMod(self.data)
        self.trend_a = TrendA(self.data, ma_type=MAType.EMA, ma_period=7, ma_period_smoothing=7)
        self.kdj = KDJIndicator(self.data, period=9, smooth=3)
        self.rsi = ChainerRSIHisto(self.data, period_rsi=14, period_signal=9)
        self.rsrs = RSRSIndicator(self.data, period=15, std_period=100)
        self.qqe = QQECalc(self.data, rsi_len=6, rsi_smooth=5, qqe_factor=3.0)


def _run_capture():
    dataframe = _dataframe()
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(_IndicatorCapture)
    cerebro.adddata(bt.feeds.PandasData(dataname=dataframe, datetime="datetime"))
    cerebro.broker.setcash(100000.0)
    strategy = cerebro.run()[0]
    length = len(dataframe)
    return {
        "pivot_high": _line_values(strategy.pivot_high.l.pivothigh, length),
        "pivot_low": _line_values(strategy.pivot_low.l.pivotlow, length),
        "super_trend": {
            "up": _line_values(strategy.super_trend.l.up, length),
            "dn": _line_values(strategy.super_trend.l.dn, length),
            "trend": _line_values(strategy.super_trend.l.trend, length),
            "buy_signal": _line_values(strategy.super_trend.l.buy_signal, length),
            "sell_signal": _line_values(strategy.super_trend.l.sell_signal, length),
        },
        "qqe_mod": {
            "secondary_qqe_trend_line": _line_values(strategy.qqe_mod.l.secondary_qqe_trend_line, length),
            "secondary_rsi_histogram": _line_values(strategy.qqe_mod.l.secondary_rsi_histogram, length),
            "qqe_up_signal": _line_values(strategy.qqe_mod.l.qqe_up_signal, length),
            "qqe_down_signal": _line_values(strategy.qqe_mod.l.qqe_down_signal, length),
            "bollinger_upper": _line_values(strategy.qqe_mod.l.bollinger_upper, length),
            "bollinger_lower": _line_values(strategy.qqe_mod.l.bollinger_lower, length),
        },
        "trend_a": {
            "open": _line_values(strategy.trend_a.l.open_line, length),
            "close": _line_values(strategy.trend_a.l.close_line, length),
            "high": _line_values(strategy.trend_a.l.high_line, length),
            "low": _line_values(strategy.trend_a.l.low_line, length),
            "highest_body": _line_values(strategy.trend_a.l.highest_body_line, length),
            "lowest_body": _line_values(strategy.trend_a.l.lowest_body_line, length),
            "trend": _line_values(strategy.trend_a.l.trend, length),
        },
        "kdj": {
            "K": _line_values(strategy.kdj.l.K, length),
            "D": _line_values(strategy.kdj.l.D, length),
            "J": _line_values(strategy.kdj.l.J, length),
        },
        "chainerrsi": {
            "rsi": _line_values(strategy.rsi.l.rsi, length),
            "signal": _line_values(strategy.rsi.l.signal, length),
            "histo": _line_values(strategy.rsi.l.histo, length),
        },
        "rsrs": {
            "beta": _line_values(strategy.rsrs.l.beta, length),
            "zscore": _line_values(strategy.rsrs.l.zscore, length),
        },
        "qqe": {
            "trendline": _line_values(strategy.qqe.l.trendline, length),
            "smoothed_rsi": _line_values(strategy.qqe.l.smoothed_rsi, length),
        },
    }


def _round_floats(value):
    if isinstance(value, dict):
        return {key: _round_floats(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_floats(item) for item in value]
    if isinstance(value, float):
        return round(value, 12)
    return value


def test_indicator_outputs_match_pre_kernel_move_snapshot():
    payload = _round_floats(_run_capture())

    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    assert digest == GOLDEN_SHA256
