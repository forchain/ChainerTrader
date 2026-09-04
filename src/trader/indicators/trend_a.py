"""
Trend Indicator A (v2.2)

Based on Pine Script v2.2:
Flow: Raw OHLC -> HA conversion -> MA (ma_period) -> MA (ma_period_smoothing)

Pine Script logic:
    o = f_ma_type(ma_type, open, ma_period)     # Expression definition
    ha = ticker.heikinashi(syminfo.tickerid)    # Get HA data source
    ha_o = request.security(ha, tf, o)          # Execute expression on HA data

This means: first get HA data, then apply MA on HA OHLC.
"""

import logging
import math

import backtrader as bt

from trader.utils.ma import MAType

logger = logging.getLogger(__name__)

SUPPORTED_MA_TYPES = (MAType.EMA, MAType.SMA, MAType.WMA)


def f_ma_type(line, ma_type, period):
    """Create MA indicator based on type."""
    if ma_type == MAType.SMA:
        return bt.ind.SMA(line, period=period)
    if ma_type == MAType.WMA:
        return bt.ind.WeightedMovingAverage(line, period=period)
    return bt.ind.EMA(line, period=period)


class TrendA(bt.Indicator):
    """
    Trend Indicator A based on Pine Script v2.2 logic.

    Calculation flow (matching Pine Script exactly):
    1. Heikin Ashi conversion of raw OHLC (using bt.ind.HeikinAshi)
    2. First Smoothing: MA of HA OHLC (ma_period)
    3. Second Smoothing: MA of Step 2 result (ma_period_smoothing)
    """

    lines = (
        'open_line',
        'close_line',
        'high_line',
        'low_line',
        'highest_body_line',
        'lowest_body_line',
        'trend',
    )

    params = dict(
        ma_type=MAType.EMA,
        ma_period=7,
        ma_period_smoothing=7,
        debug_times=None,
    )

    plotinfo = dict(subplot=False)

    plotlines = dict(
        open_line=dict(color='blue', _name='Open Line', linewidth=1.0),
        close_line=dict(color='#26A69A', _name='Close Line', linewidth=2.0),
        high_line=dict(color='green', _name='High Line', linewidth=1.0),
        low_line=dict(color='red', _name='Low Line', linewidth=1.0),
        highest_body_line=dict(_plotskip=True),
        lowest_body_line=dict(_plotskip=True),
        trend=dict(_plotskip=True),
    )

    def __init__(self):
        if self.p.ma_type not in SUPPORTED_MA_TYPES:
            supported = ", ".join(t.value for t in SUPPORTED_MA_TYPES)
            raise ValueError(f"TrendA supports: {supported}. Got: {self.p.ma_type}")

        self._debug_timestamps = list(self.p.debug_times) if self.p.debug_times else []

        # Step 1: Heikin Ashi conversion of raw OHLC
        self.ha = bt.ind.HeikinAshi(self.data)

        # Step 2: First smoothing - MA of HA OHLC (ma_period)
        ha_o_ma = f_ma_type(self.ha.ha_open, self.p.ma_type, self.p.ma_period)
        ha_c_ma = f_ma_type(self.ha.ha_close, self.p.ma_type, self.p.ma_period)
        ha_h_ma = f_ma_type(self.ha.ha_high, self.p.ma_type, self.p.ma_period)
        ha_l_ma = f_ma_type(self.ha.ha_low, self.p.ma_type, self.p.ma_period)

        # Step 3: Second smoothing - MA of Step 2 result (ma_period_smoothing)
        self.smooth_o = f_ma_type(ha_o_ma, self.p.ma_type, self.p.ma_period_smoothing)
        self.smooth_c = f_ma_type(ha_c_ma, self.p.ma_type, self.p.ma_period_smoothing)
        self.smooth_h = f_ma_type(ha_h_ma, self.p.ma_type, self.p.ma_period_smoothing)
        self.smooth_l = f_ma_type(ha_l_ma, self.p.ma_type, self.p.ma_period_smoothing)

        # Store for debug
        self._ha_o_ma = ha_o_ma
        self._ha_c_ma = ha_c_ma
        self._ha_h_ma = ha_h_ma
        self._ha_l_ma = ha_l_ma

    def next(self):
        open_line = self.smooth_o[0]
        close_line = self.smooth_c[0]
        high_line = self.smooth_h[0]
        low_line = self.smooth_l[0]

        self.l.open_line[0] = open_line
        self.l.close_line[0] = close_line
        self.l.high_line[0] = high_line
        self.l.low_line[0] = low_line

        self.l.highest_body_line[0] = max(open_line, close_line)
        self.l.lowest_body_line[0] = min(open_line, close_line)

        diff = high_line - low_line
        self.l.trend[0] = (
            100 * (close_line - open_line) / diff if not math.isclose(diff, 0.0) else 0
        )

        # Debug
        if self._debug_timestamps:
            ts = int(bt.num2date(self.data.datetime[0]).timestamp())
            if ts in self._debug_timestamps:
                logger.info("===== TrendA Debug [time=%s] =====", ts)
                ma_o, ma_c = self._ha_o_ma[0], self._ha_c_ma[0]
                ma_h, ma_l = self._ha_h_ma[0], self._ha_l_ma[0]
                logger.info(
                    "Step1 MA(%s) on HA: O=%.3f C=%.3f H=%.3f L=%.3f",
                    self.p.ma_period,
                    ma_o,
                    ma_c,
                    ma_h,
                    ma_l,
                )
                logger.info(
                    "Step2 MA(%s) on Step1: O=%.3f C=%.3f H=%.3f L=%.3f",
                    self.p.ma_period_smoothing,
                    open_line,
                    close_line,
                    high_line,
                    low_line,
                )
