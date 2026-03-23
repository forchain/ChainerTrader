"""
MACD Triple Divergence Strategy

Implements MACD histogram triple top/bottom divergence detection for the ChainerTrader framework.

Strategy Logic (Based on "MACD柱形图三段顶背离和三段底背离" document):

Bottom Divergence (做多信号):
- Requires 3 consecutive red (negative) histogram segments (R1, R2, R3)
- Each red segment separated by a green (positive) or near-zero segment
- Price makes lower lows: P1 > P2 > P3 (declining)
- MACD histogram absolute values decrease: |M1| > |M2| > |M3| (red bars getting shorter)
- Signal triggered when R3 segment completes (histogram turns positive or near-zero)

Top Divergence (做空信号):
- Requires 3 consecutive green (positive) histogram segments (G1, G2, G3)
- Each green segment separated by a red (negative) or near-zero segment
- Price makes higher highs: H1 < H2 < H3 (rising)
- MACD histogram values decrease: G1_max > G2_max > G3_max (green bars getting shorter)
- Signal triggered when G3 segment completes (histogram turns negative or near-zero)

Special Stop Loss:
- After entering on bottom divergence, if histogram becomes more negative than entry bar,
  the structure is invalidated and position should be closed immediately
- Same logic (mirrored) for top divergence short positions
"""

from __future__ import absolute_import, division, print_function, unicode_literals

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Optional

import backtrader as bt

from trader.strategy.base_strategy import BaseStrategy


class SegmentSign(Enum):
    """Sign of a MACD histogram segment."""
    NEGATIVE = -1  # Red bars (hist < 0)
    ZERO = 0       # Near-zero bars
    POSITIVE = 1   # Green bars (hist > 0)


@dataclass
class Segment:
    """Represents a continuous segment of MACD histogram with the same sign."""
    start_idx: int          # Bar index where segment starts
    end_idx: int            # Bar index where segment ends (inclusive)
    sign: SegmentSign       # Sign of the segment
    extreme_val: float      # Most extreme value (min for negative, max for positive)
    extreme_idx: int        # Bar index of extreme value
    price_extreme: float    # Corresponding price extreme (low for negative, high for positive)
    price_extreme_idx: int  # Bar index of price extreme


class MacdTripleDivergenceStrategy(BaseStrategy):
    """
    MACD Triple Divergence Strategy using ChainerTrader framework.

    Detects triple bottom divergence (long signal) and triple top divergence (short signal)
    based on MACD histogram patterns.
    """

    params = (
        ("name", "MACDTripleDivergence"),
        # MACD parameters
        ("macd_fast", 12),
        ("macd_slow", 26),
        ("macd_signal", 9),
        # Divergence detection parameters
        ("opp_ratio", 0.35),           # Max ratio of separator segment to reference segment
        ("zero_eps", 0.0001),          # Absolute value below this is considered near-zero
        ("price_eps", 0.0),            # Price comparison tolerance (0 = strict)
        ("macd_eps", 0.0),             # MACD comparison tolerance (0 = strict)
        ("max_lookback_segments", 10), # Max segments to keep in history
        ("max_lookback_bars", 200),    # Max bars to look back for divergence
        # Chainer Framework parameters
        ("chainer_mode", "LONG_ONLY"),  # LONG_ONLY, SHORT_ONLY, BOTH
        ("chainer_auto_signal", True),  # Enable auto signal processing
        ("chainer_stoploss_atr_mult", 1.0),
        ("chainer_enter_need_confirm", True),
        ("chainer_exit_need_confirm", True),
        ("chainer_enable_breakeven", True),
        ("chainer_risk_reward_ratio", 2.0),
        # Special MACD-based stop loss
        ("macd_stop_enabled", True),   # Enable MACD-based stop loss
        ("macd_stop_eps", 0.0001),     # Tolerance for MACD stop comparison
        # Disable new entries when equity falls below this percentage of initial account value (0 = disabled)
        ("chainer_min_equity_percent", 0.0),
    )

    def __init__(self):
        super().__init__()

        # Initialize MACD indicator
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.params.macd_fast,
            period_me2=self.params.macd_slow,
            period_signal=self.params.macd_signal,
        )
        # MACD histogram = MACD line - Signal line
        self.macd_hist = self.macd.macd - self.macd.signal

        # Segment tracking
        self._segments: Deque[Segment] = deque(maxlen=self.params.max_lookback_segments)
        self._current_segment: Optional[Segment] = None
        self._prev_hist_sign: Optional[SegmentSign] = None

        # Special stop loss tracking
        self._entry_hist_val: Optional[float] = None
        self._entry_direction: Optional[str] = None

        # Order tracking
        self.order = None

        self.log_info(
            f"MACDTripleDivergence 初始化: macd=({self.params.macd_fast},{self.params.macd_slow},{self.params.macd_signal}) "
            f"opp_ratio={self.params.opp_ratio} chainer_mode={self.params.chainer_mode}"
        )

    def _get_sign(self, hist_val: float) -> SegmentSign:
        """Determine the sign of a histogram value."""
        if abs(hist_val) <= self.params.zero_eps:
            return SegmentSign.ZERO
        return SegmentSign.POSITIVE if hist_val > 0 else SegmentSign.NEGATIVE

    def _update_segments(self):
        """Update segment tracking based on current histogram value."""
        if len(self) < 2:
            return

        hist_val = float(self.macd_hist[0])
        current_sign = self._get_sign(hist_val)
        bar_idx = self.bar_idx()

        # Initialize on first bar with data
        if self._current_segment is None:
            price_val = float(self.data.low[0]) if current_sign == SegmentSign.NEGATIVE else float(self.data.high[0])
            self._current_segment = Segment(
                start_idx=bar_idx,
                end_idx=bar_idx,
                sign=current_sign,
                extreme_val=hist_val,
                extreme_idx=bar_idx,
                price_extreme=price_val,
                price_extreme_idx=bar_idx,
            )
            self._prev_hist_sign = current_sign
            return

        # Check if sign changed (considering ZERO as potential transition)
        sign_changed = False
        if current_sign != self._prev_hist_sign:
            # ZERO can be part of either segment, only change on clear sign flip
            if current_sign != SegmentSign.ZERO and self._prev_hist_sign != SegmentSign.ZERO:
                sign_changed = True
            elif current_sign != SegmentSign.ZERO and self._current_segment.sign != current_sign:
                # Transitioning from ZERO to a definite sign different from current segment
                sign_changed = True

        if sign_changed:
            # Close current segment and add to history
            self._segments.append(self._current_segment)

            # Start new segment
            price_val = float(self.data.low[0]) if current_sign == SegmentSign.NEGATIVE else float(self.data.high[0])
            self._current_segment = Segment(
                start_idx=bar_idx,
                end_idx=bar_idx,
                sign=current_sign,
                extreme_val=hist_val,
                extreme_idx=bar_idx,
                price_extreme=price_val,
                price_extreme_idx=bar_idx,
            )
        else:
            # Update current segment
            self._current_segment.end_idx = bar_idx

            # Update extreme values
            if self._current_segment.sign == SegmentSign.NEGATIVE:
                # For negative segment, track minimum (most negative)
                if hist_val < self._current_segment.extreme_val:
                    self._current_segment.extreme_val = hist_val
                    self._current_segment.extreme_idx = bar_idx
                # Track lowest price
                low_price = float(self.data.low[0])
                if low_price < self._current_segment.price_extreme:
                    self._current_segment.price_extreme = low_price
                    self._current_segment.price_extreme_idx = bar_idx
            elif self._current_segment.sign == SegmentSign.POSITIVE:
                # For positive segment, track maximum
                if hist_val > self._current_segment.extreme_val:
                    self._current_segment.extreme_val = hist_val
                    self._current_segment.extreme_idx = bar_idx
                # Track highest price
                high_price = float(self.data.high[0])
                if high_price > self._current_segment.price_extreme:
                    self._current_segment.price_extreme = high_price
                    self._current_segment.price_extreme_idx = bar_idx

        self._prev_hist_sign = current_sign

    def _detect_bottom_triple_divergence(self) -> bool:
        """
        Detect triple bottom divergence (bullish signal).

        Conditions:
        1. Three red (negative) segments R1, R2, R3 with separator segments between them
        2. Price makes lower lows: P1 > P2 > P3
        3. MACD histogram absolute values decrease: |M1| > |M2| > |M3|
        4. Separator segments are relatively small (controlled by opp_ratio)

        Returns:
            bool: True if triple bottom divergence detected
        """
        # Need at least 5 segments: R1, Sep1, R2, Sep2, R3
        # Plus current segment might be the signal (turning positive after R3)
        segments = list(self._segments)

        # Signal on transition from negative to positive/zero
        if self._current_segment is None:
            return False

        # We need the R3 segment to be complete (current segment is different sign)
        if self._current_segment.sign != SegmentSign.NEGATIVE:
            # Current segment is not negative, check if we just completed R3
            if len(segments) < 5:
                return False

            # Find the pattern: R1, Sep1, R2, Sep2, R3 in recent history
            # Look backwards from the end of segments
            r3 = None
            sep2 = None
            r2 = None
            sep1 = None
            r1 = None

            idx = len(segments) - 1
            # Find R3 (most recent negative segment)
            while idx >= 0:
                if segments[idx].sign == SegmentSign.NEGATIVE:
                    r3 = segments[idx]
                    break
                idx -= 1

            if r3 is None or idx < 4:
                return False

            # Find Sep2 (segment before R3)
            idx -= 1
            sep2 = segments[idx]

            # Find R2
            idx -= 1
            while idx >= 0:
                if segments[idx].sign == SegmentSign.NEGATIVE:
                    r2 = segments[idx]
                    break
                idx -= 1

            if r2 is None or idx < 2:
                return False

            # Find Sep1 (segment before R2)
            idx -= 1
            sep1 = segments[idx]

            # Find R1
            idx -= 1
            while idx >= 0:
                if segments[idx].sign == SegmentSign.NEGATIVE:
                    r1 = segments[idx]
                    break
                idx -= 1

            if r1 is None:
                return False

            # Check lookback limit
            if self.bar_idx() - r1.start_idx > self.params.max_lookback_bars:
                return False

            # Get extreme values (most negative histogram values in each red segment)
            m1 = abs(r1.extreme_val)
            m2 = abs(r2.extreme_val)
            m3 = abs(r3.extreme_val)

            # Get price lows
            p1 = r1.price_extreme
            p2 = r2.price_extreme
            p3 = r3.price_extreme

            # Check MACD condition: |M1| > |M2| > |M3| (red bars getting shorter)
            if not (m1 > m2 + self.params.macd_eps and m2 > m3 + self.params.macd_eps):
                return False

            # Check price condition: P1 > P2 > P3 (price making lower lows)
            if not (p1 > p2 + self.params.price_eps and p2 > p3 + self.params.price_eps):
                return False

            # Check separator segments (should be relatively small)
            h_ref = max(m1, m2, m3)

            # Sep1 check
            sep1_max = abs(sep1.extreme_val) if sep1.sign == SegmentSign.POSITIVE else 0
            if sep1_max > self.params.opp_ratio * h_ref:
                return False

            # Sep2 check
            sep2_max = abs(sep2.extreme_val) if sep2.sign == SegmentSign.POSITIVE else 0
            if sep2_max > self.params.opp_ratio * h_ref:
                return False

            self.log_info(
                f"三段底背离检测: R1({r1.start_idx}-{r1.end_idx}, M={r1.extreme_val:.6f}, P={p1:.2f}) "
                f"R2({r2.start_idx}-{r2.end_idx}, M={r2.extreme_val:.6f}, P={p2:.2f}) "
                f"R3({r3.start_idx}-{r3.end_idx}, M={r3.extreme_val:.6f}, P={p3:.2f})"
            )
            return True

        return False

    def _detect_top_triple_divergence(self) -> bool:
        """
        Detect triple top divergence (bearish signal).

        Conditions:
        1. Three green (positive) segments G1, G2, G3 with separator segments between them
        2. Price makes higher highs: H1 < H2 < H3
        3. MACD histogram values decrease: G1_max > G2_max > G3_max
        4. Separator segments are relatively small (controlled by opp_ratio)

        Returns:
            bool: True if triple top divergence detected
        """
        segments = list(self._segments)

        if self._current_segment is None:
            return False

        # We need the G3 segment to be complete (current segment is different sign)
        if self._current_segment.sign != SegmentSign.POSITIVE:
            if len(segments) < 5:
                return False

            # Find the pattern: G1, Sep1, G2, Sep2, G3 in recent history
            g3 = None
            sep2 = None
            g2 = None
            sep1 = None
            g1 = None

            idx = len(segments) - 1
            # Find G3 (most recent positive segment)
            while idx >= 0:
                if segments[idx].sign == SegmentSign.POSITIVE:
                    g3 = segments[idx]
                    break
                idx -= 1

            if g3 is None or idx < 4:
                return False

            # Find Sep2
            idx -= 1
            sep2 = segments[idx]

            # Find G2
            idx -= 1
            while idx >= 0:
                if segments[idx].sign == SegmentSign.POSITIVE:
                    g2 = segments[idx]
                    break
                idx -= 1

            if g2 is None or idx < 2:
                return False

            # Find Sep1
            idx -= 1
            sep1 = segments[idx]

            # Find G1
            idx -= 1
            while idx >= 0:
                if segments[idx].sign == SegmentSign.POSITIVE:
                    g1 = segments[idx]
                    break
                idx -= 1

            if g1 is None:
                return False

            # Check lookback limit
            if self.bar_idx() - g1.start_idx > self.params.max_lookback_bars:
                return False

            # Get extreme values (maximum histogram values in each green segment)
            m1 = g1.extreme_val
            m2 = g2.extreme_val
            m3 = g3.extreme_val

            # Get price highs
            h1 = g1.price_extreme
            h2 = g2.price_extreme
            h3 = g3.price_extreme

            # Check MACD condition: M1 > M2 > M3 (green bars getting shorter)
            if not (m1 > m2 + self.params.macd_eps and m2 > m3 + self.params.macd_eps):
                return False

            # Check price condition: H1 < H2 < H3 (price making higher highs)
            if not (h1 + self.params.price_eps < h2 and h2 + self.params.price_eps < h3):
                return False

            # Check separator segments (should be relatively small)
            h_ref = max(m1, m2, m3)

            # Sep1 check (negative segment)
            sep1_max = abs(sep1.extreme_val) if sep1.sign == SegmentSign.NEGATIVE else 0
            if sep1_max > self.params.opp_ratio * h_ref:
                return False

            # Sep2 check
            sep2_max = abs(sep2.extreme_val) if sep2.sign == SegmentSign.NEGATIVE else 0
            if sep2_max > self.params.opp_ratio * h_ref:
                return False

            self.log_info(
                f"三段顶背离检测: G1({g1.start_idx}-{g1.end_idx}, M={m1:.6f}, H={h1:.2f}) "
                f"G2({g2.start_idx}-{g2.end_idx}, M={m2:.6f}, H={h2:.2f}) "
                f"G3({g3.start_idx}-{g3.end_idx}, M={m3:.6f}, H={h3:.2f})"
            )
            return True

        return False

    def get_long_signal(self) -> bool:
        """
        Generate long signal based on triple bottom divergence.

        Returns:
            bool: True when triple bottom divergence is detected.
        """
        if len(self) < self.params.macd_slow + self.params.macd_signal:
            return False

        return self._detect_bottom_triple_divergence()

    def get_short_signal(self) -> bool:
        """
        Generate short signal based on triple top divergence.

        Returns:
            bool: True when triple top divergence is detected.
        """
        if len(self) < self.params.macd_slow + self.params.macd_signal:
            return False

        return self._detect_top_triple_divergence()

    def _check_macd_stop_loss(self) -> bool:
        """
        Check if MACD-based stop loss should be triggered.

        For long positions (bottom divergence entry):
        - If current histogram becomes more negative than entry histogram, exit

        For short positions (top divergence entry):
        - If current histogram becomes more positive than entry histogram, exit

        Returns:
            bool: True if MACD stop loss should be triggered
        """
        if not self.params.macd_stop_enabled:
            return False

        if self._entry_hist_val is None or self._entry_direction is None:
            return False

        pos_size = float(getattr(self.position, "size", 0.0))
        if pos_size == 0.0:
            return False

        hist_val = float(self.macd_hist[0])

        if self._entry_direction == "LONG":
            # For long, check if histogram became more negative
            if hist_val < self._entry_hist_val - self.params.macd_stop_eps:
                self.log_info(
                    f"MACD止损触发(多): entry_hist={self._entry_hist_val:.6f} "
                    f"current_hist={hist_val:.6f}"
                )
                return True
        elif self._entry_direction == "SHORT":
            # For short, check if histogram became more positive
            if hist_val > self._entry_hist_val + self.params.macd_stop_eps:
                self.log_info(
                    f"MACD止损触发(空): entry_hist={self._entry_hist_val:.6f} "
                    f"current_hist={hist_val:.6f}"
                )
                return True

        return False

    def notify_order(self, order):
        """Track entry for MACD stop loss logic."""
        super().notify_order(order)

        if order.status == order.Completed:
            # Check if this is an entry order
            role = getattr(order, "info", {}).get("chainer_role")
            if role == "entry":
                # Record entry histogram value for MACD stop loss
                self._entry_hist_val = float(self.macd_hist[0])
                self._entry_direction = "LONG" if order.isbuy() else "SHORT"
                self.log_info(
                    f"记录入场MACD柱: direction={self._entry_direction} "
                    f"hist={self._entry_hist_val:.6f}"
                )
            elif role == "exit" or role == "stop" or role == "take_profit":
                # Clear entry tracking on exit
                self._entry_hist_val = None
                self._entry_direction = None

    def next(self):
        """Main strategy logic executed on each bar."""
        # Update segment tracking
        self._update_segments()

        # Call parent next() for signal processing
        super().next()

        # Skip if order is pending
        if self.order:
            return

        # Skip if not enough data
        if len(self) < self.params.macd_slow + self.params.macd_signal:
            return

        # Check for MACD-based stop loss (special exit condition)
        if self._check_macd_stop_loss():
            # Force exit via exit_trade
            pos_size = float(getattr(self.position, "size", 0.0))
            if pos_size != 0.0:
                try:
                    self.exit_trade(key_bar_index=self.bar_idx(), need_confirm=False)
                except (ValueError, RuntimeError) as e:
                    self.log_debug(f"MACD stop loss exit_trade failed: {e}")
                    # Fallback to direct close
                    self.close()

        # Signal processing is handled by BaseStrategy._process_signals()
        # when chainer_auto_signal is True
