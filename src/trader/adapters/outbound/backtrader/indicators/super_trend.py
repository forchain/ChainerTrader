"""
SuperTrend Indicator

Based on Pine Script v6:
- ATR-based trend following indicator
- Outputs up/dn bands and trend direction
- Includes buy/sell signals
"""

import logging

import backtrader as bt

from trader.core.strategy.domain.indicators import SuperTrendKernel

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
        self._kernel = SuperTrendKernel(self.p.multiplier)

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

        values = self._kernel.update(src=src, atr=atr, close=close, close_prev=close_prev)

        self.l.up[0] = values.up
        self.l.dn[0] = values.dn
        self.l.trend[0] = values.trend
        self.l.buy_signal[0] = values.buy_signal
        self.l.sell_signal[0] = values.sell_signal

        # Debug logging
        if self._debug_timestamps:
            current_bt_time = self.data.datetime[0]
            current_timestamp = int(bt.num2date(current_bt_time).timestamp())

            if current_timestamp in self._debug_timestamps:
                logger.info(f"===== SuperTrend Debug [time={current_timestamp}] =====")
                logger.info(f"Input: close={close:.2f} close_prev={close_prev:.2f}")
                logger.info(f"ATR({self.p.periods}): atr={atr:.4f} src={src:.2f}")
                logger.info(f"Raw: up_raw={values.up_raw:.2f} dn_raw={values.dn_raw:.2f}")
                logger.info(f"Prev: up_prev={values.up_prev:.2f} dn_prev={values.dn_prev:.2f} trend_prev={values.trend_prev}")
                logger.info(f"Calc: up={values.up:.2f} dn={values.dn:.2f} trend={values.trend}")
                logger.info(f"Signal: buy={1 if values.is_buy else 0} sell={1 if values.is_sell else 0}")
