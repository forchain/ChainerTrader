"""
QQE MOD Indicator

Based on Pine Script v6:
- Dual QQE calculation (Primary + Secondary)
- Bollinger Bands applied to Primary QQE Trend Line
- Outputs: Secondary QQE trend line, RSI histogram, up/down signals
"""

import logging
import math

import backtrader as bt

from trader.core.strategy.domain.indicators import QQEBandKernel, QQEModKernel

logger = logging.getLogger(__name__)


class QQEBand(bt.Indicator):
    """
    QQE Band calculator - helper indicator for recursive QQE calculations.

    Calculation:
    1. Calculate RSI and smooth it with EMA
    2. Calculate ATR of smoothed RSI
    3. Calculate dynamic bands (longBand/shortBand) with recursive adjustment
    4. Determine trend direction based on RSI crossing bands
    5. Output trend line based on trend direction
    """

    lines = ("qqe_trend_line", "smoothed_rsi", "long_band", "short_band", "trend_direction")

    params = (
        ("rsi_length", 6),
        ("smoothing_factor", 5),
        ("qqe_factor", 3.0),
        ("debug_times", None),
    )

    plotinfo = dict(subplot=True)

    def __init__(self):
        # Parse debug timestamps
        self._debug_timestamps = list(self.p.debug_times) if self.p.debug_times else []

        self._kernel = QQEBandKernel(rsi_length=self.p.rsi_length, qqe_factor=self.p.qqe_factor)

        # RSI and smoothed RSI
        self.rsi = bt.ind.RSI(self.data.close, period=self.p.rsi_length)
        self.smoothed_rsi_line = bt.ind.EMA(self.rsi, period=self.p.smoothing_factor)

    def next(self):
        values = self._kernel.update(self.smoothed_rsi_line[0])

        self.l.qqe_trend_line[0] = values.qqe_trend_line
        self.l.smoothed_rsi[0] = values.smoothed_rsi
        self.l.long_band[0] = values.long_band
        self.l.short_band[0] = values.short_band
        self.l.trend_direction[0] = values.trend_direction


class QQEMod(bt.Indicator):
    """
    QQE MOD indicator based on Pine Script v6 logic.

    Calculation:
    1. Calculate Primary QQE (rsi_length_primary, rsi_smoothing_primary, qqe_factor_primary)
    2. Calculate Secondary QQE (rsi_length_secondary, rsi_smoothing_secondary, qqe_factor_secondary)
    3. Apply Bollinger Bands to (Primary QQE Trend Line - 50)
    4. Generate up/down signals based on RSI vs Bollinger Bands and threshold
    """

    lines = (
        "secondary_qqe_trend_line",
        "secondary_rsi_histogram",
        "qqe_up_signal",
        "qqe_down_signal",
        "bollinger_upper",
        "bollinger_lower",
    )

    params = (
        ("rsi_length_primary", 6),
        ("rsi_smoothing_primary", 5),
        ("qqe_factor_primary", 3.0),
        ("threshold_primary", 3.0),
        ("rsi_length_secondary", 6),
        ("rsi_smoothing_secondary", 5),
        ("qqe_factor_secondary", 1.61),
        ("threshold_secondary", 3.0),
        ("bollinger_length", 50),
        ("bollinger_multiplier", 0.35),
        ("debug_times", None),
    )

    plotinfo = dict(subplot=True)

    plotlines = dict(
        secondary_qqe_trend_line=dict(color="white", _name="QQE Trend", linewidth=2.0),
        secondary_rsi_histogram=dict(
            color="gray",
            _name="RSI Histogram",
            _method="bar",
            alpha=0.5,
        ),
        qqe_up_signal=dict(
            color="#00c3ff",
            _name="Up Signal",
            _method="bar",
            alpha=0.8,
        ),
        qqe_down_signal=dict(
            color="#ff0062",
            _name="Down Signal",
            _method="bar",
            alpha=0.8,
        ),
        bollinger_upper=dict(_plotskip=True),
        bollinger_lower=dict(_plotskip=True),
    )

    def __init__(self):
        # Parse debug timestamps
        self._debug_timestamps = list(self.p.debug_times) if self.p.debug_times else []

        # Primary QQE
        self.p_qqe = QQEBand(
            self.data,
            rsi_length=self.p.rsi_length_primary,
            smoothing_factor=self.p.rsi_smoothing_primary,
            qqe_factor=self.p.qqe_factor_primary,
        )

        # Secondary QQE
        self.s_qqe = QQEBand(
            self.data,
            rsi_length=self.p.rsi_length_secondary,
            smoothing_factor=self.p.rsi_smoothing_secondary,
            qqe_factor=self.p.qqe_factor_secondary,
        )

        # Bollinger Bands on (Primary QQE Trend Line - 50)
        # We need to calculate this after QQEBand outputs are available
        # So we'll do it in next() method
        self._kernel = QQEModKernel(
            threshold_secondary=self.p.threshold_secondary,
            bollinger_length=self.p.bollinger_length,
            bollinger_multiplier=self.p.bollinger_multiplier,
        )

    def next(self):
        # Get QQE values
        primary_qqe_trend_line = self.p_qqe.l.qqe_trend_line[0]
        primary_rsi = self.p_qqe.l.smoothed_rsi[0]
        secondary_qqe_trend_line = self.s_qqe.l.qqe_trend_line[0]
        secondary_rsi = self.s_qqe.l.smoothed_rsi[0]

        values = self._kernel.update(
            primary_qqe_trend_line=primary_qqe_trend_line,
            primary_rsi=primary_rsi,
            secondary_qqe_trend_line=secondary_qqe_trend_line,
            secondary_rsi=secondary_rsi,
        )

        self.l.secondary_qqe_trend_line[0] = values.secondary_qqe_trend_line
        self.l.secondary_rsi_histogram[0] = values.secondary_rsi_histogram
        self.l.qqe_up_signal[0] = values.qqe_up_signal
        self.l.qqe_down_signal[0] = values.qqe_down_signal
        self.l.bollinger_upper[0] = values.bollinger_upper
        self.l.bollinger_lower[0] = values.bollinger_lower

        # Debug logging
        if self._debug_timestamps:
            current_bt_time = self.data.datetime[0]
            current_timestamp = int(bt.num2date(current_bt_time).timestamp())

            if current_timestamp in self._debug_timestamps:
                logger.info(f"===== QQE MOD Debug [time={current_timestamp}] =====")
                logger.info(f"Input: close={self.data.close[0]:.2f}")
                logger.info(
                    f"Primary RSI: smoothedRsi={primary_rsi:.4f}"
                )
                logger.info(
                    f"Primary QQE: longBand={self.p_qqe.l.long_band[0]:.4f} "
                    f"shortBand={self.p_qqe.l.short_band[0]:.4f} "
                    f"trend={self.p_qqe.l.trend_direction[0]:.0f} "
                    f"trendLine={primary_qqe_trend_line:.4f}"
                )
                logger.info(f"Secondary RSI: smoothedRsi={secondary_rsi:.4f}")
                logger.info(
                    f"Secondary QQE: longBand={self.s_qqe.l.long_band[0]:.4f} "
                    f"shortBand={self.s_qqe.l.short_band[0]:.4f} "
                    f"trend={self.s_qqe.l.trend_direction[0]:.0f} "
                    f"trendLine={secondary_qqe_trend_line:.4f}"
                )
                logger.info(f"Bollinger: upper={values.bollinger_upper:.4f} lower={values.bollinger_lower:.4f}")
                logger.info(f"Output: secTrendLine-50={values.secondary_qqe_trend_line:.4f} secRSI-50={values.secondary_rsi_histogram:.4f}")
                logger.info(
                    f"Signals: upCond={not math.isnan(values.qqe_up_signal)} "
                    f"downCond={not math.isnan(values.qqe_down_signal)}"
                )
