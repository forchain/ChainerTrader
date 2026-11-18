"""Framework-free indicator calculation kernels.

The backtrader indicator classes in ``trader.indicators`` only feed inputs into
these kernels and copy the results onto their lines.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import statsmodels.api as sm


@dataclass(frozen=True)
class SuperTrendValues:
    up: float
    dn: float
    trend: int
    buy_signal: float
    sell_signal: float
    up_raw: float
    dn_raw: float
    up_prev: float
    dn_prev: float
    trend_prev: int
    is_buy: bool
    is_sell: bool


class SuperTrendKernel:
    def __init__(self, multiplier: float):
        self.multiplier = float(multiplier)
        self._up_prev: float | None = None
        self._dn_prev: float | None = None
        self._trend_prev = 1

    def update(self, *, src: float, atr: float, close: float, close_prev: float) -> SuperTrendValues:
        up_raw = src - self.multiplier * atr
        dn_raw = src + self.multiplier * atr

        up_prev = self._up_prev if self._up_prev is not None else up_raw
        dn_prev = self._dn_prev if self._dn_prev is not None else dn_raw
        trend_prev = self._trend_prev

        if close_prev > up_prev:
            up = max(up_raw, up_prev)
        else:
            up = up_raw

        if close_prev < dn_prev:
            dn = min(dn_raw, dn_prev)
        else:
            dn = dn_raw

        if trend_prev == -1 and close > dn_prev:
            trend = 1
        elif trend_prev == 1 and close < up_prev:
            trend = -1
        else:
            trend = trend_prev

        is_buy = trend == 1 and trend_prev == -1
        is_sell = trend == -1 and trend_prev == 1

        self._up_prev = up
        self._dn_prev = dn
        self._trend_prev = trend

        return SuperTrendValues(
            up=up if trend == 1 else math.nan,
            dn=dn if trend == -1 else math.nan,
            trend=trend,
            buy_signal=up if is_buy else math.nan,
            sell_signal=dn if is_sell else math.nan,
            up_raw=up_raw,
            dn_raw=dn_raw,
            up_prev=up_prev,
            dn_prev=dn_prev,
            trend_prev=trend_prev,
            is_buy=is_buy,
            is_sell=is_sell,
        )


@dataclass(frozen=True)
class QQEBandValues:
    qqe_trend_line: float
    smoothed_rsi: float
    long_band: float
    short_band: float
    trend_direction: int


class QQEBandKernel:
    def __init__(self, *, rsi_length: int, qqe_factor: float):
        self.qqe_factor = float(qqe_factor)
        self._wilders_length = int(rsi_length) * 2 - 1
        self._long_band_prev: float | None = None
        self._short_band_prev: float | None = None
        self._trend_prev = 0
        self._smoothed_rsi_prev: float | None = None
        self._smoothed_atr_rsi: float | None = None

    def update(self, smoothed_rsi: float) -> QQEBandValues:
        smoothed_rsi_prev = self._smoothed_rsi_prev if self._smoothed_rsi_prev is not None else smoothed_rsi

        atr_rsi = abs(smoothed_rsi_prev - smoothed_rsi)
        if self._smoothed_atr_rsi is None:
            self._smoothed_atr_rsi = atr_rsi
        else:
            alpha = 2.0 / (self._wilders_length + 1)
            self._smoothed_atr_rsi = alpha * atr_rsi + (1 - alpha) * self._smoothed_atr_rsi

        atr_delta = self._smoothed_atr_rsi * self.qqe_factor
        new_long_band = smoothed_rsi - atr_delta
        new_short_band = smoothed_rsi + atr_delta

        long_band_prev = self._long_band_prev if self._long_band_prev is not None else new_long_band
        short_band_prev = self._short_band_prev if self._short_band_prev is not None else new_short_band
        trend_prev = self._trend_prev

        if smoothed_rsi_prev > long_band_prev and smoothed_rsi > long_band_prev:
            long_band = max(long_band_prev, new_long_band)
        else:
            long_band = new_long_band

        if smoothed_rsi_prev < short_band_prev and smoothed_rsi < short_band_prev:
            short_band = min(short_band_prev, new_short_band)
        else:
            short_band = new_short_band

        cross_up = (smoothed_rsi_prev <= short_band_prev and smoothed_rsi > short_band_prev) or (
            smoothed_rsi_prev >= short_band_prev and smoothed_rsi < short_band_prev
        )
        cross_down = (long_band_prev <= smoothed_rsi_prev and long_band_prev > smoothed_rsi) or (
            long_band_prev >= smoothed_rsi_prev and long_band_prev < smoothed_rsi
        )

        if cross_up:
            trend = 1
        elif cross_down:
            trend = -1
        else:
            trend = trend_prev

        qqe_trend_line = long_band if trend == 1 else short_band

        self._long_band_prev = long_band
        self._short_band_prev = short_band
        self._trend_prev = trend
        self._smoothed_rsi_prev = smoothed_rsi

        return QQEBandValues(
            qqe_trend_line=qqe_trend_line,
            smoothed_rsi=smoothed_rsi,
            long_band=long_band,
            short_band=short_band,
            trend_direction=trend,
        )


@dataclass(frozen=True)
class QQEModValues:
    secondary_qqe_trend_line: float
    secondary_rsi_histogram: float
    qqe_up_signal: float
    qqe_down_signal: float
    bollinger_upper: float
    bollinger_lower: float


class QQEModKernel:
    def __init__(self, *, threshold_secondary: float, bollinger_length: int, bollinger_multiplier: float):
        self.threshold_secondary = float(threshold_secondary)
        self.bollinger_length = int(bollinger_length)
        self.bollinger_multiplier = float(bollinger_multiplier)
        self._bb_values: list[float] = []

    def update(
        self,
        *,
        primary_qqe_trend_line: float,
        primary_rsi: float,
        secondary_qqe_trend_line: float,
        secondary_rsi: float,
    ) -> QQEModValues:
        bb_value = primary_qqe_trend_line - 50
        self._bb_values.append(bb_value)
        if len(self._bb_values) > self.bollinger_length:
            self._bb_values = self._bb_values[-self.bollinger_length :]

        if len(self._bb_values) >= self.bollinger_length:
            # fsum: CPython 3.12+ compensates builtin sum(), which shifted the golden snapshot by ~1e-13 on 3.11
            bb_basis = math.fsum(self._bb_values) / len(self._bb_values)
            variance = math.fsum((x - bb_basis) ** 2 for x in self._bb_values) / len(self._bb_values)
            bb_std = variance**0.5
            bb_deviation = self.bollinger_multiplier * bb_std
            bb_upper = bb_basis + bb_deviation
            bb_lower = bb_basis - bb_deviation
        else:
            bb_upper = 0
            bb_lower = 0

        sec_trend_line = secondary_qqe_trend_line - 50
        sec_rsi = secondary_rsi - 50
        pri_rsi = primary_rsi - 50

        up_condition = sec_rsi > self.threshold_secondary and pri_rsi > bb_upper
        down_condition = sec_rsi < -self.threshold_secondary and pri_rsi < bb_lower

        return QQEModValues(
            secondary_qqe_trend_line=sec_trend_line,
            secondary_rsi_histogram=sec_rsi,
            qqe_up_signal=sec_rsi if up_condition else math.nan,
            qqe_down_signal=sec_rsi if down_condition else math.nan,
            bollinger_upper=bb_upper,
            bollinger_lower=bb_lower,
        )


def is_pivot_high(values: Sequence[float], *, right: int) -> bool:
    mid = len(values) - 1 - right
    mid_val = values[mid]
    for index, value in enumerate(values):
        if index == mid:
            continue
        if value >= mid_val:
            return False
    return True


def is_pivot_low(values: Sequence[float], *, right: int) -> bool:
    mid = len(values) - 1 - right
    mid_val = values[mid]
    for index, value in enumerate(values):
        if index == mid:
            continue
        if value <= mid_val:
            return False
    return True


def rsrs_beta(lows: Sequence[float], highs: Sequence[float]) -> float:
    temp = sm.add_constant(np.asarray(lows))
    model = sm.OLS(np.asarray(highs), temp).fit()
    return model.params[1]


def rsrs_zscore(beta: float, beta_series: Sequence[float]) -> float:
    beta_values = np.asarray(beta_series)
    beta_mean = np.mean(beta_values)
    beta_std = np.std(beta_values)
    return (beta - beta_mean) / beta_std if beta_std != 0 else 0
