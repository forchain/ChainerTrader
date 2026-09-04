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

        # State variables for recursive calculations
        self._long_band_prev = None
        self._short_band_prev = None
        self._trend_prev = 0
        self._smoothed_rsi_prev = None

        # Wilder's smoothing length
        wilders_length = self.p.rsi_length * 2 - 1

        # RSI and smoothed RSI
        self.rsi = bt.ind.RSI(self.data.close, period=self.p.rsi_length)
        self.smoothed_rsi_line = bt.ind.EMA(self.rsi, period=self.p.smoothing_factor)

        # ATR of RSI (will be calculated in next() due to recursive dependency)
        self._wilders_length = wilders_length

    def next(self):
        smoothed_rsi = self.smoothed_rsi_line[0]
        smoothed_rsi_prev = self._smoothed_rsi_prev if self._smoothed_rsi_prev is not None else smoothed_rsi

        # Calculate ATR of RSI: |smoothedRsi[1] - smoothedRsi|
        atr_rsi = abs(smoothed_rsi_prev - smoothed_rsi)

        # Smoothed ATR RSI using simple EMA approximation
        # For proper EMA, we need to track it recursively
        if not hasattr(self, "_smoothed_atr_rsi"):
            self._smoothed_atr_rsi = atr_rsi
        else:
            alpha = 2.0 / (self._wilders_length + 1)
            self._smoothed_atr_rsi = alpha * atr_rsi + (1 - alpha) * self._smoothed_atr_rsi

        atr_delta = self._smoothed_atr_rsi * self.p.qqe_factor

        # Calculate new bands
        new_long_band = smoothed_rsi - atr_delta
        new_short_band = smoothed_rsi + atr_delta

        # Get previous values
        long_band_prev = self._long_band_prev if self._long_band_prev is not None else new_long_band
        short_band_prev = self._short_band_prev if self._short_band_prev is not None else new_short_band
        trend_prev = self._trend_prev

        # Recursive long band calculation:
        # longBand := smoothedRsi[1] > longBand[1] and smoothedRsi > longBand[1] ? max(longBand[1], newLongBand) : newLongBand
        if smoothed_rsi_prev > long_band_prev and smoothed_rsi > long_band_prev:
            long_band = max(long_band_prev, new_long_band)
        else:
            long_band = new_long_band

        # Recursive short band calculation:
        # shortBand := smoothedRsi[1] < shortBand[1] and smoothedRsi < shortBand[1] ? min(shortBand[1], newShortBand) : newShortBand
        if smoothed_rsi_prev < short_band_prev and smoothed_rsi < short_band_prev:
            short_band = min(short_band_prev, new_short_band)
        else:
            short_band = new_short_band

        # Trend direction based on crosses
        # if ta.cross(smoothedRsi, shortBand[1]) -> trendDirection := 1
        # else if ta.cross(longBand[1], smoothedRsi) -> trendDirection := -1
        # else -> trendDirection := trendDirection[1]
        cross_up = (smoothed_rsi_prev <= short_band_prev and smoothed_rsi > short_band_prev) or \
                   (smoothed_rsi_prev >= short_band_prev and smoothed_rsi < short_band_prev)
        cross_down = (long_band_prev <= smoothed_rsi_prev and long_band_prev > smoothed_rsi) or \
                     (long_band_prev >= smoothed_rsi_prev and long_band_prev < smoothed_rsi)

        if cross_up:
            trend = 1
        elif cross_down:
            trend = -1
        else:
            trend = trend_prev

        # QQE trend line
        qqe_trend_line = long_band if trend == 1 else short_band

        # Store output values
        self.l.qqe_trend_line[0] = qqe_trend_line
        self.l.smoothed_rsi[0] = smoothed_rsi
        self.l.long_band[0] = long_band
        self.l.short_band[0] = short_band
        self.l.trend_direction[0] = trend

        # Update state for next iteration
        self._long_band_prev = long_band
        self._short_band_prev = short_band
        self._trend_prev = trend
        self._smoothed_rsi_prev = smoothed_rsi


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

    def next(self):
        # Get QQE values
        primary_qqe_trend_line = self.p_qqe.l.qqe_trend_line[0]
        primary_rsi = self.p_qqe.l.smoothed_rsi[0]
        secondary_qqe_trend_line = self.s_qqe.l.qqe_trend_line[0]
        secondary_rsi = self.s_qqe.l.smoothed_rsi[0]

        # Initialize Bollinger Bands state if not exists
        if not hasattr(self, "_bb_values"):
            self._bb_values = []

        # Add current value to Bollinger calculation
        bb_value = primary_qqe_trend_line - 50
        self._bb_values.append(bb_value)

        # Keep only bollinger_length values
        if len(self._bb_values) > self.p.bollinger_length:
            self._bb_values = self._bb_values[-self.p.bollinger_length:]

        # Calculate Bollinger Bands
        if len(self._bb_values) >= self.p.bollinger_length:
            bb_basis = sum(self._bb_values) / len(self._bb_values)
            variance = sum((x - bb_basis) ** 2 for x in self._bb_values) / len(self._bb_values)
            bb_std = variance ** 0.5
            bb_deviation = self.p.bollinger_multiplier * bb_std
            bb_upper = bb_basis + bb_deviation
            bb_lower = bb_basis - bb_deviation
        else:
            bb_upper = 0
            bb_lower = 0

        # Calculate output values (all offset by -50)
        sec_trend_line = secondary_qqe_trend_line - 50
        sec_rsi = secondary_rsi - 50
        pri_rsi = primary_rsi - 50

        # Signal conditions (matching Pine Script exactly):
        # qqeUpCondition = secondaryRSI - 50 > thresholdSecondary and primaryRSI - 50 > bollingerUpper
        # qqeDownCondition = secondaryRSI - 50 < -thresholdSecondary and primaryRSI - 50 < bollingerLower
        up_condition = sec_rsi > self.p.threshold_secondary and pri_rsi > bb_upper
        down_condition = sec_rsi < -self.p.threshold_secondary and pri_rsi < bb_lower

        # Store output values
        self.l.secondary_qqe_trend_line[0] = sec_trend_line
        self.l.secondary_rsi_histogram[0] = sec_rsi
        self.l.qqe_up_signal[0] = sec_rsi if up_condition else math.nan
        self.l.qqe_down_signal[0] = sec_rsi if down_condition else math.nan
        self.l.bollinger_upper[0] = bb_upper
        self.l.bollinger_lower[0] = bb_lower

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
                logger.info(f"Bollinger: upper={bb_upper:.4f} lower={bb_lower:.4f}")
                logger.info(f"Output: secTrendLine-50={sec_trend_line:.4f} secRSI-50={sec_rsi:.4f}")
                logger.info(f"Signals: upCond={up_condition} downCond={down_condition}")
