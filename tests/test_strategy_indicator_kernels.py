import math

import pytest

from trader.core.strategy.domain.indicators import (
    QQEBandKernel,
    QQEModKernel,
    SuperTrendKernel,
    is_pivot_high,
    is_pivot_low,
    rsrs_beta,
    rsrs_zscore,
)


def test_super_trend_kernel_flips_direction_and_emits_signals():
    kernel = SuperTrendKernel(3.0)

    first = kernel.update(src=100.0, atr=2.0, close=100.0, close_prev=99.0)
    assert first.up == 94.0
    assert math.isnan(first.dn)
    assert first.trend == 1

    sell = kernel.update(src=101.0, atr=2.0, close=90.0, close_prev=100.0)
    assert math.isnan(sell.up)
    assert sell.dn == 106.0
    assert sell.trend == -1
    assert sell.sell_signal == 106.0
    assert sell.is_sell

    buy = kernel.update(src=104.0, atr=2.0, close=110.0, close_prev=99.0)
    assert buy.up == 98.0
    assert math.isnan(buy.dn)
    assert buy.trend == 1
    assert buy.buy_signal == 98.0
    assert buy.is_buy


def test_qqe_band_kernel_tracks_bands_and_trend_direction():
    kernel = QQEBandKernel(rsi_length=6, qqe_factor=3.0)

    values = [kernel.update(rsi) for rsi in (50.0, 52.0, 49.0, 55.0)]

    assert [(value.qqe_trend_line, value.trend_direction) for value in values] == [
        (50.0, 0),
        (51.0, 1),
        (pytest.approx(51.333333333333), -1),
        (pytest.approx(50.055555555556), 1),
    ]


def test_qqe_mod_kernel_applies_bollinger_thresholds_and_signals():
    kernel = QQEModKernel(threshold_secondary=3.0, bollinger_length=3, bollinger_multiplier=0.35)

    values = [
        kernel.update(
            primary_qqe_trend_line=primary,
            primary_rsi=primary_rsi,
            secondary_qqe_trend_line=secondary,
            secondary_rsi=secondary_rsi,
        )
        for primary, primary_rsi, secondary, secondary_rsi in (
            (50, 50, 50, 50),
            (60, 60, 55, 60),
            (70, 70, 60, 70),
            (80, 80, 65, 80),
        )
    ]

    assert values[0].bollinger_upper == 0
    assert math.isnan(values[0].qqe_up_signal)
    assert values[-1].secondary_qqe_trend_line == 15
    assert values[-1].secondary_rsi_histogram == 30
    assert values[-1].qqe_up_signal == 30
    assert math.isnan(values[-1].qqe_down_signal)
    assert values[-1].bollinger_upper == pytest.approx(22.857738033247)
    assert values[-1].bollinger_lower == pytest.approx(17.142261966753)


def test_pivot_kernels_use_strict_window_comparisons():
    high_window = [1.0, 2.0, 5.0, 2.0, 1.0]
    assert is_pivot_high(high_window, right=2)
    assert not is_pivot_high([1.0, 2.0, 5.0, 5.0, 1.0], right=2)

    low_window = [5.0, 4.0, 1.0, 4.0, 5.0]
    assert is_pivot_low(low_window, right=2)
    assert not is_pivot_low([5.0, 4.0, 1.0, 1.0, 5.0], right=2)


def test_rsrs_kernels_are_pure_numeric_calculations():
    assert rsrs_beta([1.0, 2.0, 3.0, 4.0, 5.0], [3.0, 5.0, 7.0, 9.0, 11.0]) == 2.0
    assert rsrs_zscore(2.0, [2.0, 2.0, 2.0]) == 0
