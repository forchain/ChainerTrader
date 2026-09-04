"""
SuperTrend Indicator

Based on Pine Script v6:
- ATR-based trend following indicator
- Outputs up/dn bands and trend direction
- Includes buy/sell signals
"""

import logging
import math

import backtrader as bt

logger = logging.getLogger(__name__)


class SuperTrend(bt.Indicator):
    """
    SuperTrend indicator based on Pine Script v6 logic.

    Calculation:
    1. src = (high + low) / 2
    2. atr = ATR(periods) or SMA(TR, periods)
    3. up = src - multiplier * atr (with recursive adjustment)
    4. dn = src + multiplier * atr (with recursive adjustment)
    5. trend = 1 (up) or -1 (down) based on close vs bands
    """

    lines = ("up", "dn", "trend", "buy_signal", "sell_signal")

    params = (
        ("periods", 10),
        ("multiplier", 3.0),
        ("change_atr", True),  # True: use ATR, False: use SMA of TR
        ("debug_times", None),  # List of timestamps in seconds for debugging
    )

    plotinfo = dict(subplot=False)

    plotlines = dict(
        # Up band: only visible when trend == 1 (using NaN for invisible)
        up=dict(color="green", _name="Up Trend", linewidth=2.0),
        # Down band: only visible when trend == -1 (using NaN for invisible)
        dn=dict(color="red", _name="Down Trend", linewidth=2.0),
        trend=dict(_plotskip=True),
        # Buy signal: marker at up band when trend changes from -1 to 1
        buy_signal=dict(
            color="green",
            _name="Buy",
            marker="^",
            markersize=10.0,
            fillstyle="full",
            ls="",  # No line, only markers
        ),
        # Sell signal: marker at dn band when trend changes from 1 to -1
        sell_signal=dict(
            color="red",
            _name="Sell",
            marker="v",
            markersize=10.0,
            fillstyle="full",
            ls="",  # No line, only markers
        ),
    )

    def __init__(self):
        # State variables for recursive calculation
        self._up_prev = None
        self._dn_prev = None
        self._trend_prev = 1  # Default trend is up (1)

        # Parse debug_times parameter
        self._debug_timestamps = (
            list(self.p.debug_times) if self.p.debug_times else []
        )

        # Vectorized calculations (high performance)
        self.src = (self.data.high + self.data.low) / 2

        # ATR calculation
        if self.p.change_atr:
            self.atr = bt.ind.ATR(self.data, period=self.p.periods)
        else:
            self.atr = bt.ind.SMA(bt.ind.TrueRange(self.data), period=self.p.periods)

    def next(self):
        # Get current values
        src = self.src[0]
        atr = self.atr[0]
        close = self.data.close[0]
        close_prev = self.data.close[-1] if len(self.data) > 1 else close

        # Calculate raw up/dn bands
        up_raw = src - self.p.multiplier * atr
        dn_raw = src + self.p.multiplier * atr

        # Get previous values (or use raw values for first bar)
        up_prev = self._up_prev if self._up_prev is not None else up_raw
        dn_prev = self._dn_prev if self._dn_prev is not None else dn_raw
        trend_prev = self._trend_prev

        # Recursive up calculation: up := close[1] > up1 ? max(up, up1) : up
        if close_prev > up_prev:
            up = max(up_raw, up_prev)
        else:
            up = up_raw

        # Recursive dn calculation: dn := close[1] < dn1 ? min(dn, dn1) : dn
        if close_prev < dn_prev:
            dn = min(dn_raw, dn_prev)
        else:
            dn = dn_raw

        # Trend calculation:
        # trend := trend == -1 and close > dn1 ? 1 : trend == 1 and close < up1 ? -1 : trend
        if trend_prev == -1 and close > dn_prev:
            trend = 1
        elif trend_prev == 1 and close < up_prev:
            trend = -1
        else:
            trend = trend_prev

        # Buy/Sell signals (show at the band price, or NaN if no signal)
        is_buy = trend == 1 and trend_prev == -1
        is_sell = trend == -1 and trend_prev == 1
        buy_signal = up if is_buy else math.nan
        sell_signal = dn if is_sell else math.nan

        # Store output values
        # Only show up band when trend == 1, dn band when trend == -1
        # This matches TradingView behavior: trend == 1 ? up : na
        self.l.up[0] = up if trend == 1 else math.nan
        self.l.dn[0] = dn if trend == -1 else math.nan
        self.l.trend[0] = trend
        self.l.buy_signal[0] = buy_signal
        self.l.sell_signal[0] = sell_signal

        # Debug logging
        if self._debug_timestamps:
            current_bt_time = self.data.datetime[0]
            current_timestamp = int(bt.num2date(current_bt_time).timestamp())

            if current_timestamp in self._debug_timestamps:
                logger.info(f"===== SuperTrend Debug [time={current_timestamp}] =====")
                logger.info(f"Input: close={close:.2f} close_prev={close_prev:.2f}")
                logger.info(f"ATR({self.p.periods}): atr={atr:.4f} src={src:.2f}")
                logger.info(f"Raw: up_raw={up_raw:.2f} dn_raw={dn_raw:.2f}")
                logger.info(f"Prev: up_prev={up_prev:.2f} dn_prev={dn_prev:.2f} trend_prev={trend_prev}")
                logger.info(f"Calc: up={up:.2f} dn={dn:.2f} trend={trend}")
                logger.info(f"Signal: buy={1 if is_buy else 0} sell={1 if is_sell else 0}")

        # Update state for next iteration
        self._up_prev = up
        self._dn_prev = dn
        self._trend_prev = trend
