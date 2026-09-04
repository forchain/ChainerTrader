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
from typing import Deque, List, Optional

import backtrader as bt

from trader.strategy.base_strategy import BaseStrategy

DEFAULT_NOISE_CLUSTER_RATIO = 0.10
DEFAULT_WEAK_WAVE_FILTER_RATIO = 0.11
DEFAULT_TRIGGER_LATEST_LEG_MIN_RATIO = 0.10


class SegmentSign(Enum):
    """Sign of a MACD histogram segment."""

    NEGATIVE = -1  # Red bars (hist < 0)
    ZERO = 0  # Near-zero bars
    POSITIVE = 1  # Green bars (hist > 0)


@dataclass
class Segment:
    """Represents a continuous segment of MACD histogram with the same sign."""

    start_idx: int  # Bar index where segment starts
    end_idx: int  # Bar index where segment ends (inclusive)
    sign: SegmentSign  # Sign of the segment
    extreme_val: float  # Most extreme value (min for negative, max for positive)
    extreme_idx: int  # Bar index of extreme value
    price_extreme: float  # Corresponding price extreme (low for negative, high for positive)
    price_extreme_idx: int  # Bar index of price extreme


@dataclass
class Pivot:
    """Represents a local MACD pivot within a wave."""

    wave: Segment
    idx: int
    macd_val: float
    price_val: float


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
        ("noise_cluster_ratio", DEFAULT_NOISE_CLUSTER_RATIO),  # Zero-axis noise threshold for wave split and separator near-zero checks
        ("weak_wave_filter_ratio", DEFAULT_WEAK_WAVE_FILTER_RATIO),  # Minimum same-sign wave strength ratio to keep a wave
        (
            "trigger_latest_leg_min_ratio",
            DEFAULT_TRIGGER_LATEST_LEG_MIN_RATIO,
        ),  # Minimum latest-leg strength ratio required to actually trigger a signal
        ("second_leg_min_ratio", 0.20),  # Minimum M2/M1 ratio for a valid three-leg structure
        ("zero_eps", 0.0001),  # Absolute value below this is considered near-zero
        ("price_eps", 0.0),  # Price comparison tolerance (0 = strict)
        ("macd_eps", 0.0),  # MACD comparison tolerance (0 = strict)
        ("max_lookback_segments", 10),  # Max segments to keep in history
        ("max_lookback_bars", 200),  # Hard safety cap for recent bars scanned
        ("max_same_sign_waves", 5),  # Max same-sign waves to consider from the latest wave backward
        # Chainer Framework parameters
        ("chainer_mode", "BOTH"),  # LONG_ONLY, SHORT_ONLY, BOTH
        ("chainer_stoploss_atr_mult", 0.0),
        ("chainer_need_confirm", False),
        ("chainer_enable_breakeven", False),
        ("chainer_risk_reward_ratio", 0.0),
        # Special MACD-based stop loss
        ("macd_stop_enabled", True),  # Enable MACD-based stop loss
        ("macd_stop_eps", 0.0001),  # Tolerance for MACD stop comparison
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
        self._entry_signal_bar_idx: Optional[int] = None
        self._pending_entry_signal_bar_idx: Optional[int] = None
        self._pending_entry_hist_val: Optional[float] = None
        self._last_long_signal_bar_idx: Optional[int] = None
        self._last_short_signal_bar_idx: Optional[int] = None
        self._last_long_structure_key: Optional[tuple] = None
        self._last_long_price_extreme: Optional[float] = None
        self._last_short_structure_key: Optional[tuple] = None
        self._last_short_price_extreme: Optional[float] = None
        self._long_signal_meta: Optional[dict] = None
        self._short_signal_meta: Optional[dict] = None
        self._signal_seq: int = 0
        self._signal_events: List[dict] = []

        # Order tracking
        self.order = None

        self.log_info(
            f"MACDTripleDivergence 初始化: macd=({self.params.macd_fast},{self.params.macd_slow},{self.params.macd_signal}) "
            f"noise_cluster_ratio={self.params.noise_cluster_ratio} weak_wave_filter_ratio={self.params.weak_wave_filter_ratio} "
            f"trigger_latest_leg_min_ratio={self.params.trigger_latest_leg_min_ratio} "
            f"chainer_mode={self.params.chainer_mode}"
        )

    def start(self):
        super().start()
        self.broker.set_coc(True)

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

    def _build_recent_waves(self) -> List[Segment]:
        """
        Build MACD waves from history up to the previous bar.

        A new wave starts when:
        1. Histogram flips color, or
        2. Histogram retraces near zero and then expands again in the same direction.

        This models the document's "相反颜色出现，或者非常接近出现".
        """
        if len(self) < 3:
            return []

        lookback = min(self.params.max_lookback_bars, len(self) - 1)
        bars = []
        current_idx = self.bar_idx()
        for ago in range(lookback, 0, -1):
            bars.append(
                {
                    "idx": current_idx - ago,
                    "hist": float(self.macd_hist[-ago]),
                    "high": float(self.data.high[-ago]),
                    "low": float(self.data.low[-ago]),
                }
            )

        waves: List[Segment] = []
        current_wave: Optional[Segment] = None
        ready_split = False

        for pos, bar in enumerate(bars):
            sign = self._get_sign(bar["hist"])

            if sign == SegmentSign.ZERO:
                if current_wave is not None:
                    current_wave.end_idx = bar["idx"]
                    if current_wave.extreme_idx < bar["idx"] and abs(bar["hist"]) <= abs(current_wave.extreme_val) * self.params.noise_cluster_ratio:
                        ready_split = True
                continue

            if current_wave is None:
                price_val = bar["low"] if sign == SegmentSign.NEGATIVE else bar["high"]
                current_wave = Segment(
                    start_idx=bar["idx"],
                    end_idx=bar["idx"],
                    sign=sign,
                    extreme_val=bar["hist"],
                    extreme_idx=bar["idx"],
                    price_extreme=price_val,
                    price_extreme_idx=bar["idx"],
                )
                ready_split = False
                continue

            if sign != current_wave.sign:
                waves.append(current_wave)
                price_val = bar["low"] if sign == SegmentSign.NEGATIVE else bar["high"]
                current_wave = Segment(
                    start_idx=bar["idx"],
                    end_idx=bar["idx"],
                    sign=sign,
                    extreme_val=bar["hist"],
                    extreme_idx=bar["idx"],
                    price_extreme=price_val,
                    price_extreme_idx=bar["idx"],
                )
                ready_split = False
                continue

            if ready_split and current_wave.extreme_idx < bar["idx"] and pos > 0:
                prev_hist = bars[pos - 1]["hist"]
                if abs(bar["hist"]) > abs(prev_hist) + self.params.macd_eps:
                    waves.append(current_wave)
                    price_val = bar["low"] if sign == SegmentSign.NEGATIVE else bar["high"]
                    current_wave = Segment(
                        start_idx=bar["idx"],
                        end_idx=bar["idx"],
                        sign=sign,
                        extreme_val=bar["hist"],
                        extreme_idx=bar["idx"],
                        price_extreme=price_val,
                        price_extreme_idx=bar["idx"],
                    )
                    ready_split = False
                    continue

            current_wave.end_idx = bar["idx"]

            if current_wave.sign == SegmentSign.NEGATIVE:
                if bar["hist"] < current_wave.extreme_val:
                    current_wave.extreme_val = bar["hist"]
                    current_wave.extreme_idx = bar["idx"]
                    ready_split = False
                if bar["low"] < current_wave.price_extreme:
                    current_wave.price_extreme = bar["low"]
                    current_wave.price_extreme_idx = bar["idx"]
            else:
                if bar["hist"] > current_wave.extreme_val:
                    current_wave.extreme_val = bar["hist"]
                    current_wave.extreme_idx = bar["idx"]
                    ready_split = False
                if bar["high"] > current_wave.price_extreme:
                    current_wave.price_extreme = bar["high"]
                    current_wave.price_extreme_idx = bar["idx"]

            if current_wave.extreme_idx < bar["idx"] and abs(bar["hist"]) <= abs(current_wave.extreme_val) * self.params.noise_cluster_ratio:
                ready_split = True

        if current_wave is not None:
            waves.append(current_wave)

        return waves

    def _is_first_shortening_bar(self, sign: SegmentSign) -> bool:
        """Return True only on the first bar after a local histogram extreme starts shrinking."""
        if len(self) < 3:
            return False

        prev_prev_hist = float(self.macd_hist[-2])
        prev_hist = float(self.macd_hist[-1])
        current_hist = float(self.macd_hist[0])

        if sign == SegmentSign.POSITIVE:
            return (
                prev_hist > self.params.zero_eps
                and prev_hist > prev_prev_hist + self.params.macd_eps
                and current_hist < prev_hist - self.params.macd_eps
            )

        if sign == SegmentSign.NEGATIVE:
            return (
                prev_hist < -self.params.zero_eps
                and prev_hist < prev_prev_hist - self.params.macd_eps
                and current_hist > prev_hist + self.params.macd_eps
            )

        return False

    def _shift_from_bar_index(self, bar_idx: int) -> int:
        return int(bar_idx) - self.bar_idx()

    def _bar_snapshot(self, bar_idx: int) -> dict:
        shift = self._shift_from_bar_index(bar_idx)
        dt = bt.num2date(self.data.datetime[shift]).isoformat()
        return {
            "time": dt,
            "open": float(self.data.open[shift]),
            "high": float(self.data.high[shift]),
            "low": float(self.data.low[shift]),
            "close": float(self.data.close[shift]),
            "macd_hist": float(self.macd_hist[shift]),
        }

    def _price_on_bar(self, bar_idx: int, sign: SegmentSign) -> float:
        shift = self._shift_from_bar_index(bar_idx)
        if sign == SegmentSign.NEGATIVE:
            return float(self.data.low[shift])
        return float(self.data.high[shift])

    def _price_on_macd_extreme_bar(self, wave: Segment) -> float:
        return self._price_on_bar(wave.extreme_idx, wave.sign)

    def _wave_price_extreme_before_macd_extreme(self, wave: Segment) -> tuple[float, int]:
        start_idx = int(wave.start_idx)
        end_idx = int(wave.extreme_idx)

        if wave.sign == SegmentSign.NEGATIVE:
            best_idx = min(range(start_idx, end_idx + 1), key=lambda idx: float(self.data.low[self._shift_from_bar_index(idx)]))
            best_price = float(self.data.low[self._shift_from_bar_index(best_idx)])
        else:
            best_idx = max(range(start_idx, end_idx + 1), key=lambda idx: float(self.data.high[self._shift_from_bar_index(idx)]))
            best_price = float(self.data.high[self._shift_from_bar_index(best_idx)])

        return best_price, best_idx

    def _wave_structure_price(self, wave: Segment) -> float:
        price, _ = self._wave_price_extreme_before_macd_extreme(wave)
        return price

    def _wave_structure_price_idx(self, wave: Segment) -> int:
        _, idx = self._wave_price_extreme_before_macd_extreme(wave)
        return idx

    def _wave_candidate_price(self, wave: Segment) -> float:
        return float(self._price_on_macd_extreme_bar(wave))

    def _wave_directional_price_extreme(self, wave: Segment, direction: str) -> float:
        start_idx = int(wave.start_idx)
        end_idx = int(wave.end_idx)

        if direction == "LONG":
            return min(float(self.data.low[self._shift_from_bar_index(idx)]) for idx in range(start_idx, end_idx + 1))

        return max(float(self.data.high[self._shift_from_bar_index(idx)]) for idx in range(start_idx, end_idx + 1))

    def _wave_advances_directional_price(self, previous: Segment, current: Segment, sign: SegmentSign) -> bool:
        direction = "SHORT" if sign == SegmentSign.POSITIVE else "LONG"
        previous_price = self._wave_directional_price_extreme(previous, direction)
        current_price = self._wave_directional_price_extreme(current, direction)
        return (
            current_price > previous_price + self.params.price_eps
            if sign == SegmentSign.POSITIVE
            else current_price < previous_price - self.params.price_eps
        )

    def _wave_beats_separator_price(self, separator: Segment, current: Segment, sign: SegmentSign) -> bool:
        direction = "SHORT" if sign == SegmentSign.POSITIVE else "LONG"
        separator_price = self._wave_directional_price_extreme(separator, direction)
        current_price = self._wave_directional_price_extreme(current, direction)
        return (
            current_price > separator_price + self.params.price_eps
            if sign == SegmentSign.POSITIVE
            else current_price < separator_price - self.params.price_eps
        )

    def _wave_extends_macd_extreme(self, previous: Segment, current: Segment, sign: SegmentSign) -> bool:
        return (
            float(current.extreme_val) > float(previous.extreme_val) + self.params.macd_eps
            if sign == SegmentSign.POSITIVE
            else float(current.extreme_val) < float(previous.extreme_val) - self.params.macd_eps
        )

    def _is_tiny_opposite_separator(self, separator: Segment, left: Segment, right: Segment) -> bool:
        if separator.sign in (SegmentSign.ZERO, left.sign):
            return False
        threshold = min(abs(float(left.extreme_val)), abs(float(right.extreme_val))) * float(self.params.noise_cluster_ratio)
        return abs(float(separator.extreme_val)) <= threshold + self.params.macd_eps

    def _merge_same_sign_waves(self, left: Segment, right: Segment) -> Segment:
        if left.sign != right.sign:
            raise ValueError("cannot merge waves with different signs")

        if left.sign == SegmentSign.NEGATIVE:
            extreme_val, extreme_idx = (
                (left.extreme_val, left.extreme_idx)
                if float(left.extreme_val) <= float(right.extreme_val)
                else (right.extreme_val, right.extreme_idx)
            )
            price_extreme, price_extreme_idx = (
                (left.price_extreme, left.price_extreme_idx)
                if float(left.price_extreme) <= float(right.price_extreme)
                else (right.price_extreme, right.price_extreme_idx)
            )
        else:
            extreme_val, extreme_idx = (
                (left.extreme_val, left.extreme_idx)
                if float(left.extreme_val) >= float(right.extreme_val)
                else (right.extreme_val, right.extreme_idx)
            )
            price_extreme, price_extreme_idx = (
                (left.price_extreme, left.price_extreme_idx)
                if float(left.price_extreme) >= float(right.price_extreme)
                else (right.price_extreme, right.price_extreme_idx)
            )

        return Segment(
            start_idx=int(left.start_idx),
            end_idx=int(right.end_idx),
            sign=left.sign,
            extreme_val=float(extreme_val),
            extreme_idx=int(extreme_idx),
            price_extreme=float(price_extreme),
            price_extreme_idx=int(price_extreme_idx),
        )

    def _wave_owns_adjacent_price_progression(self, waves: List[Segment], wave: Segment, direction: str) -> bool:
        wave_start_idx, _ = self._wave_span_indices(waves, wave)
        if wave_start_idx <= 0:
            return True

        previous_wave = waves[wave_start_idx - 1]
        previous_extreme = self._wave_directional_price_extreme(previous_wave, direction)
        wave_extreme = self._wave_directional_price_extreme(wave, direction)

        if direction == "LONG":
            return wave_extreme < previous_extreme - self.params.price_eps

        return wave_extreme > previous_extreme + self.params.price_eps

    def _extract_wave_pivots(self, wave: Segment) -> List[Pivot]:
        pivots: List[Pivot] = []
        if int(wave.end_idx) - int(wave.start_idx) < 2:
            pivots.append(
                Pivot(
                    wave=wave,
                    idx=int(wave.extreme_idx),
                    macd_val=float(wave.extreme_val),
                    price_val=self._price_on_macd_extreme_bar(wave),
                )
            )
            return pivots

        for idx in range(int(wave.start_idx) + 1, int(wave.end_idx)):
            prev_hist = float(self.macd_hist[self._shift_from_bar_index(idx - 1)])
            curr_hist = float(self.macd_hist[self._shift_from_bar_index(idx)])
            next_hist = float(self.macd_hist[self._shift_from_bar_index(idx + 1)])

            if wave.sign == SegmentSign.POSITIVE:
                if curr_hist >= prev_hist - self.params.macd_eps and curr_hist >= next_hist - self.params.macd_eps:
                    pivots.append(
                        Pivot(
                            wave=wave,
                            idx=idx,
                            macd_val=curr_hist,
                            price_val=self._price_on_bar(idx, wave.sign),
                        )
                    )
            elif wave.sign == SegmentSign.NEGATIVE:
                if curr_hist <= prev_hist + self.params.macd_eps and curr_hist <= next_hist + self.params.macd_eps:
                    pivots.append(
                        Pivot(
                            wave=wave,
                            idx=idx,
                            macd_val=curr_hist,
                            price_val=self._price_on_bar(idx, wave.sign),
                        )
                    )

        if not pivots:
            pivots.append(
                Pivot(
                    wave=wave,
                    idx=int(wave.extreme_idx),
                    macd_val=float(wave.extreme_val),
                    price_val=self._price_on_macd_extreme_bar(wave),
                )
            )
            return pivots

        extreme_idx = int(wave.extreme_idx)
        if all(p.idx != extreme_idx for p in pivots):
            pivots.append(
                Pivot(
                    wave=wave,
                    idx=extreme_idx,
                    macd_val=float(wave.extreme_val),
                    price_val=self._price_on_macd_extreme_bar(wave),
                )
            )

        pivots.sort(key=lambda p: p.idx)
        return pivots

    def _wave_pivots(self, wave: Segment) -> List[Pivot]:
        return self._extract_wave_pivots(wave)

    def _pivot_detail(self, pivot: Pivot, direction: str) -> dict:
        snap = self._bar_snapshot(pivot.idx)
        detail = {
            "pivot_time": snap["time"],
            "pivot_bar_index": int(pivot.idx),
            "pivot_macd": round(float(pivot.macd_val), 6),
            "pivot_price": round(float(pivot.price_val), 2),
            "segment_start_bar_index": int(pivot.wave.start_idx),
            "segment_end_bar_index": int(pivot.wave.end_idx),
        }
        if direction == "LONG":
            detail["pivot_type"] = "trough"
        else:
            detail["pivot_type"] = "peak"
        return detail

    def _segment_extreme_pivot(self, wave: Segment) -> Pivot:
        return Pivot(
            wave=wave,
            idx=int(wave.extreme_idx),
            macd_val=float(wave.extreme_val),
            price_val=self._price_on_macd_extreme_bar(wave),
        )

    def _current_trigger_pivot(self, wave: Segment, sign: SegmentSign) -> Optional[Pivot]:
        prev_idx = self.bar_idx() - 1
        if prev_idx < int(wave.start_idx) or prev_idx > int(wave.end_idx):
            return None
        prev_hist = float(self.macd_hist[-1])
        if self._get_sign(prev_hist) != sign:
            return None
        return Pivot(
            wave=wave,
            idx=prev_idx,
            macd_val=prev_hist,
            price_val=self._price_on_bar(prev_idx, sign),
        )

    def _trigger_price_extreme_since_last_pivot(self, wave: Segment, trigger_pivot: Pivot) -> tuple[float, int]:
        pivots = [pivot for pivot in self._wave_pivots(wave) if int(pivot.idx) < int(trigger_pivot.idx)]
        start_idx = int(wave.start_idx) if not pivots else int(pivots[-1].idx) + 1
        end_idx = int(trigger_pivot.idx)

        if wave.sign == SegmentSign.NEGATIVE:
            best_idx = min(range(start_idx, end_idx + 1), key=lambda idx: float(self.data.low[self._shift_from_bar_index(idx)]))
            best_price = float(self.data.low[self._shift_from_bar_index(best_idx)])
        else:
            best_idx = max(range(start_idx, end_idx + 1), key=lambda idx: float(self.data.high[self._shift_from_bar_index(idx)]))
            best_price = float(self.data.high[self._shift_from_bar_index(best_idx)])

        return best_price, best_idx

    def _wave_span_indices(self, waves: List[Segment], target: Segment) -> tuple[int, int]:
        for idx, wave in enumerate(waves):
            if wave is target:
                return idx, idx

        start_idx = None
        end_idx = None
        for idx, wave in enumerate(waves):
            if (
                start_idx is None
                and wave.sign == target.sign
                and int(wave.start_idx) == int(target.start_idx)
            ):
                start_idx = idx
            if wave.sign == target.sign and int(wave.end_idx) == int(target.end_idx):
                end_idx = idx

        if start_idx is not None and end_idx is not None and start_idx <= end_idx:
            return start_idx, end_idx

        raise ValueError("target wave not found")

    def _find_wave_index(self, waves: List[Segment], target: Segment) -> int:
        start_idx, _ = self._wave_span_indices(waves, target)
        return start_idx

    def _separator_detail(self, waves: List[Segment], left: Segment, right: Segment) -> dict:
        _, left_end_idx = self._wave_span_indices(waves, left)
        right_start_idx, _ = self._wave_span_indices(waves, right)
        between = waves[left_end_idx + 1 : right_start_idx]

        mode = "opposite_color" if any(seg.sign not in (left.sign, SegmentSign.ZERO) for seg in between) else "near_zero"
        separator_abs = None
        separator_time = None
        separator_ratio = None
        ratio_gap = None
        between_start = left.extreme_idx + 1
        between_end = right.start_idx - 1
        if between_end >= between_start:
            best_idx = None
            for idx in range(between_start, between_end + 1):
                shift = self._shift_from_bar_index(idx)
                abs_hist = abs(float(self.macd_hist[shift]))
                if separator_abs is None or abs_hist < separator_abs:
                    separator_abs = abs_hist
                    best_idx = idx
            if best_idx is not None:
                separator_time = self._bar_snapshot(best_idx)["time"]

        reference_abs = abs(float(left.extreme_val))
        if separator_abs is not None and reference_abs > 0:
            separator_ratio = separator_abs / reference_abs
            ratio_gap = separator_ratio - float(self.params.noise_cluster_ratio)

        return {
            "from_time": self._bar_snapshot(left.extreme_idx)["time"],
            "to_time": self._bar_snapshot(right.extreme_idx)["time"],
            "mode": mode,
            "reference_macd_abs": round(reference_abs, 6),
            "separator_macd_abs": round(separator_abs, 6) if separator_abs is not None else None,
            "separator_time": separator_time,
            "separator_ratio": round(separator_ratio, 6) if separator_ratio is not None else None,
            "noise_cluster_ratio_threshold": float(self.params.noise_cluster_ratio),
            "near_zero_passed": separator_ratio is not None and separator_ratio <= float(self.params.noise_cluster_ratio),
            "near_zero_gap": round(ratio_gap, 6) if ratio_gap is not None else None,
            "between_wave_count": len(between),
        }

    @staticmethod
    def _structure_key(w1: Segment, w2: Segment) -> tuple:
        return (int(w1.start_idx), int(w1.extreme_idx), int(w2.start_idx), int(w2.extreme_idx))

    def _is_structural_progress(self, previous_macd_abs: float, candidate_macd_abs: float) -> bool:
        if previous_macd_abs <= 0:
            return False
        return (candidate_macd_abs / previous_macd_abs) >= float(self.params.second_leg_min_ratio)

    def _wave_half_strength(self, wave: Segment) -> float:
        if int(wave.extreme_idx) < int(wave.start_idx):
            return 0.0
        total = 0.0
        for idx in range(int(wave.start_idx), int(wave.extreme_idx) + 1):
            shift = self._shift_from_bar_index(idx)
            total += abs(float(self.macd_hist[shift]))
        return total

    def _wave_rank_strength(self, wave: Segment) -> float:
        return abs(float(wave.extreme_val))

    def _latest_leg_trigger_strength_ok(self, triplet: List[Segment]) -> bool:
        if len(triplet) < 3:
            return False
        previous_strength = self._wave_rank_strength(triplet[1])
        latest_strength = self._wave_rank_strength(triplet[2])
        if previous_strength <= 0:
            return False
        return (latest_strength / previous_strength) >= float(self.params.trigger_latest_leg_min_ratio)

    def _recent_wave_windows(self, waves: List[Segment]) -> List[List[Segment]]:
        windows: List[List[Segment]] = []
        for start in range(len(waves) - 1, -1, -1):
            windows.append(waves[start:])
        return windows

    def _bottom_triplet_structure_ok(self, triplet: List[Segment]) -> bool:
        macd_values = [abs(float(wave.extreme_val)) for wave in triplet]
        prices = [self._wave_candidate_price(wave) for wave in triplet]
        return (
            macd_values[0] > macd_values[1] + self.params.macd_eps
            and macd_values[1] > macd_values[2] + self.params.macd_eps
            and prices[0] > prices[1] + self.params.price_eps
            and prices[1] > prices[2] + self.params.price_eps
        )

    def _top_triplet_structure_ok(self, triplet: List[Segment]) -> bool:
        macd_values = [float(wave.extreme_val) for wave in triplet]
        prices = [self._wave_candidate_price(wave) for wave in triplet]
        return (
            macd_values[0] > macd_values[1] + self.params.macd_eps
            and macd_values[1] > macd_values[2] + self.params.macd_eps
            and prices[0] + self.params.price_eps < prices[1]
            and prices[1] + self.params.price_eps < prices[2]
        )

    def _bottom_trigger_price_ok(self, triplet: List[Segment], trigger_pivot: Pivot) -> tuple[bool, float]:
        third_price, _ = self._trigger_price_extreme_since_last_pivot(triplet[2], trigger_pivot)
        ok = (
            self._wave_structure_price(triplet[0]) > self._wave_structure_price(triplet[1]) + self.params.price_eps
            and self._wave_structure_price(triplet[1]) > third_price + self.params.price_eps
        )
        return ok, third_price

    def _top_trigger_price_ok(self, triplet: List[Segment], trigger_pivot: Pivot) -> tuple[bool, float]:
        third_price, _ = self._trigger_price_extreme_since_last_pivot(triplet[2], trigger_pivot)
        ok = (
            self._wave_structure_price(triplet[0]) + self.params.price_eps < self._wave_structure_price(triplet[1])
            and self._wave_structure_price(triplet[1]) + self.params.price_eps < third_price
        )
        return ok, third_price

    def _same_sign_waves(self, waves: List[Segment], sign: SegmentSign) -> List[Segment]:
        return [wave for wave in waves if wave.sign == sign]

    def _filtered_same_sign_waves(self, waves: List[Segment], sign: SegmentSign) -> List[Segment]:
        same_sign = self._same_sign_waves(waves, sign)
        if not same_sign:
            return []

        filtered: List[Segment] = [same_sign[0]]
        for idx, wave in enumerate(same_sign[1:], start=1):
            # Weak-wave filtering only removes interior noise waves; the latest leg must
            # stay available for divergence validation even when its MACD size is small.
            if idx == len(same_sign) - 1:
                filtered.append(wave)
                continue
            previous = filtered[-1]
            previous_extreme = self._wave_rank_strength(previous)
            current_extreme = self._wave_rank_strength(wave)
            if previous_extreme <= 0:
                continue
            if current_extreme / previous_extreme < float(self.params.weak_wave_filter_ratio):
                continue
            filtered.append(wave)

        return filtered

    def _same_sign_segment_count_in_triplet_window(self, waves: List[Segment], triplet: List[Segment]) -> int:
        if not triplet:
            return 0

        sign = triplet[0].sign
        first_idx, _ = self._wave_span_indices(waves, triplet[0])
        _, latest_idx = self._wave_span_indices(waves, triplet[2])
        count = 0
        previous_same_sign = False

        for wave in waves[first_idx : latest_idx + 1]:
            is_same_sign = wave.sign == sign
            if is_same_sign and not previous_same_sign:
                count += 1
            previous_same_sign = is_same_sign

        return count

    def _latest_same_sign_waves(self, waves: List[Segment], sign: SegmentSign) -> List[Segment]:
        effective: List[tuple[Segment, int]] = []
        same_sign_waves = self._filtered_same_sign_waves(waves, sign)
        wave_positions = {id(wave): idx for idx, wave in enumerate(waves)}
        for wave in same_sign_waves:
            idx = wave_positions[id(wave)]

            if not effective:
                effective.append((wave, idx))
                continue

            previous, previous_idx = effective[-1]
            if idx == previous_idx + 1:
                if self._wave_advances_directional_price(previous, wave, sign):
                    effective.append((wave, idx))
                continue

            if sign == SegmentSign.NEGATIVE and idx == previous_idx + 2:
                separator = waves[previous_idx + 1]
                if self._is_tiny_opposite_separator(separator, previous, wave):
                    advances_price = self._wave_advances_directional_price(previous, wave, sign)
                    if not advances_price:
                        continue
                    if self._wave_extends_macd_extreme(previous, wave, sign) and self._wave_beats_separator_price(separator, wave, sign):
                        effective[-1] = (self._merge_same_sign_waves(previous, wave), idx)
                        continue
                    effective.append((wave, idx))
                    continue

            effective.append((wave, idx))

        return [wave for wave, _ in effective[-int(self.params.max_same_sign_waves) :]]

    def _price_divergence_candidates(self, waves: List[Segment], sign: SegmentSign) -> List[Segment]:
        same_sign = self._latest_same_sign_waves(waves, sign)
        if not same_sign:
            return []

        latest = same_sign[-1]
        latest_price = self._wave_candidate_price(latest)

        boundary_idx = 0
        for idx in range(len(same_sign) - 2, -1, -1):
            wave_price = self._wave_candidate_price(same_sign[idx])
            if sign == SegmentSign.POSITIVE:
                if wave_price >= latest_price - self.params.price_eps:
                    boundary_idx = idx + 1
                    break
            else:
                if wave_price <= latest_price + self.params.price_eps:
                    boundary_idx = idx + 1
                    break

        return same_sign[boundary_idx:]

    @staticmethod
    def _latest_contiguous_triplet(candidates: List[Segment]) -> Optional[List[Segment]]:
        if len(candidates) < 3:
            return None
        return candidates[-3:]

    def _leg_detail(self, wave: Segment, direction: str) -> dict:
        half_strength = round(self._wave_half_strength(wave), 6)
        structure_price = self._wave_structure_price(wave)
        structure_price_idx = self._wave_structure_price_idx(wave)
        if direction == "LONG":
            return {
                "wave_start_time": self._bar_snapshot(wave.start_idx)["time"],
                "wave_end_time": self._bar_snapshot(wave.end_idx)["time"],
                "price_kline_time": self._bar_snapshot(wave.extreme_idx)["time"],
                "price_on_macd_trough_bar": round(self._price_on_macd_extreme_bar(wave), 2),
                "macd_trough_time": self._bar_snapshot(wave.extreme_idx)["time"],
                "macd_trough": round(float(wave.extreme_val), 6),
                "macd_half_strength": half_strength,
                "structure_price_low_kline_time": self._bar_snapshot(structure_price_idx)["time"],
                "structure_price_low": round(float(structure_price), 2),
                "wave_price_low_kline_time": self._bar_snapshot(wave.price_extreme_idx)["time"],
                "wave_price_low": round(float(wave.price_extreme), 2),
            }

        return {
            "wave_start_time": self._bar_snapshot(wave.start_idx)["time"],
            "wave_end_time": self._bar_snapshot(wave.end_idx)["time"],
            "price_kline_time": self._bar_snapshot(wave.extreme_idx)["time"],
            "price_on_macd_peak_bar": round(self._price_on_macd_extreme_bar(wave), 2),
            "macd_peak_time": self._bar_snapshot(wave.extreme_idx)["time"],
            "macd_peak": round(float(wave.extreme_val), 6),
            "macd_half_strength": half_strength,
            "structure_price_high_kline_time": self._bar_snapshot(structure_price_idx)["time"],
            "structure_price_high": round(float(structure_price), 2),
            "wave_price_high_kline_time": self._bar_snapshot(wave.price_extreme_idx)["time"],
            "wave_price_high": round(float(wave.price_extreme), 2),
        }

    def _triplet_to_legs(self, triplet: List[Segment], direction: str, trigger_pivot: Optional[Pivot]) -> List[dict]:
        legs = []
        for idx, wave in enumerate(triplet):
            leg = self._leg_detail(wave, direction)
            if idx == 2:
                trigger_price = float(wave.price_extreme)
                trigger_price_idx = int(wave.price_extreme_idx)
                if trigger_pivot is not None:
                    trigger_price, trigger_price_idx = self._trigger_price_extreme_since_last_pivot(wave, trigger_pivot)
                leg["trigger_price_extreme_so_far"] = round(trigger_price, 2)
                leg["trigger_price_extreme_time_so_far"] = self._bar_snapshot(trigger_price_idx)["time"]
                if trigger_pivot is not None:
                    leg["trigger_pivot_time"] = self._bar_snapshot(trigger_pivot.idx)["time"]
                    leg["trigger_pivot_macd"] = round(float(trigger_pivot.macd_val), 6)
            legs.append(leg)
        return legs

    def _signal_payload(self, direction: str, waves: List[Segment], triplet: List[Segment], trigger_pivot: Optional[Pivot]) -> dict:
        signal_bar = self._bar_snapshot(self.bar_idx())
        legs = self._triplet_to_legs(triplet, direction, trigger_pivot)
        separators = [
            self._separator_detail(waves, triplet[0], triplet[1]),
            self._separator_detail(waves, triplet[1], triplet[2]),
        ]

        if direction == "LONG":
            third_price = self._wave_structure_price(triplet[2])
            if trigger_pivot is not None:
                third_price, _ = self._trigger_price_extreme_since_last_pivot(triplet[2], trigger_pivot)
            price_values = [self._wave_structure_price(triplet[0]), self._wave_structure_price(triplet[1]), third_price]
            macd_values = [abs(float(w.extreme_val)) for w in triplet]
            conditions = {
                "price_lower_lows": {
                    "passed": price_values[0] > price_values[1] + self.params.price_eps and price_values[1] > price_values[2] + self.params.price_eps,
                    "values": [round(v, 2) for v in price_values],
                },
                "macd_higher_troughs": {
                    "passed": macd_values[0] > macd_values[1] + self.params.macd_eps and macd_values[1] > macd_values[2] + self.params.macd_eps,
                    "values": [round(v, 6) for v in macd_values],
                },
                "separator_details": separators,
                "first_shortening_bar": {
                    "passed": True,
                    "prev_hist": round(float(self.macd_hist[-1]), 6),
                    "current_hist": round(float(self.macd_hist[0]), 6),
                },
                "trigger_reason": "R3 histogram started shrinking on the signal bar",
            }
            signal_type = "bottom_divergence"
        else:
            third_price = self._wave_structure_price(triplet[2])
            if trigger_pivot is not None:
                third_price, _ = self._trigger_price_extreme_since_last_pivot(triplet[2], trigger_pivot)
            price_values = [self._wave_structure_price(triplet[0]), self._wave_structure_price(triplet[1]), third_price]
            macd_values = [float(w.extreme_val) for w in triplet]
            conditions = {
                "price_higher_highs": {
                    "passed": price_values[0] + self.params.price_eps < price_values[1] and price_values[1] + self.params.price_eps < price_values[2],
                    "values": [round(v, 2) for v in price_values],
                },
                "macd_lower_highs": {
                    "passed": macd_values[0] > macd_values[1] + self.params.macd_eps and macd_values[1] > macd_values[2] + self.params.macd_eps,
                    "values": [round(v, 6) for v in macd_values],
                },
                "separator_details": separators,
                "first_shortening_bar": {
                    "passed": True,
                    "prev_hist": round(float(self.macd_hist[-1]), 6),
                    "current_hist": round(float(self.macd_hist[0]), 6),
                },
                "trigger_reason": "G3 histogram started shrinking on the signal bar",
            }
            signal_type = "top_divergence"

        return {
            "signal_time": signal_bar["time"],
            "signal_bar_index": self.bar_idx(),
            "signal_type": signal_type,
            "signal_bar": signal_bar,
            "legs": legs,
            "conditions": conditions,
            "trade_outcome": {"status": "pending"},
        }

    def _build_signal_event(self, direction: str, waves: List[Segment], triplet: List[Segment], trigger_pivot: Optional[Pivot]) -> dict:
        payload = self._signal_payload(direction, waves, triplet, trigger_pivot)
        self._signal_seq += 1
        return {
            "signal_id": self._signal_seq,
            **payload,
        }

    def _store_signal_event(self, event: dict) -> int:
        self._signal_events.append(event)
        return int(event["signal_id"])

    def _update_signal_outcome(self, signal_id: Optional[int], status: str, **extra) -> None:
        if signal_id is None:
            return
        for event in reversed(self._signal_events):
            if int(event.get("signal_id", -1)) == int(signal_id):
                event["trade_outcome"] = {"status": status, **extra}
                return

    @staticmethod
    def _next_day_macd_follow_through_ok(direction: str, entry_hist: float, current_hist: float) -> bool:
        direction_norm = str(direction).upper()
        if direction_norm == "LONG":
            return current_hist > entry_hist
        if direction_norm == "SHORT":
            return current_hist < entry_hist
        return False

    def _find_bottom_triplet(self, waves: List[Segment], trigger_pivot: Optional[Pivot] = None) -> Optional[List[Segment]]:
        for window in self._recent_wave_windows(waves):
            candidates = self._price_divergence_candidates(window, SegmentSign.NEGATIVE)
            triplet = self._latest_contiguous_triplet(candidates)
            if triplet is None:
                continue

            if self._same_sign_segment_count_in_triplet_window(window, triplet) > int(self.params.max_same_sign_waves):
                continue
            if not self._wave_owns_adjacent_price_progression(window, triplet[1], "LONG"):
                continue
            if not self._wave_owns_adjacent_price_progression(window, triplet[2], "LONG"):
                continue
            if not self._bottom_triplet_structure_ok(triplet):
                continue
            if trigger_pivot is not None:
                trigger_price_ok, _ = self._bottom_trigger_price_ok(triplet, trigger_pivot)
                if not trigger_price_ok:
                    continue

            return triplet

        return None

    def _find_top_triplet(self, waves: List[Segment], trigger_pivot: Optional[Pivot] = None) -> Optional[List[Segment]]:
        for window in self._recent_wave_windows(waves):
            candidates = self._price_divergence_candidates(window, SegmentSign.POSITIVE)
            triplet = self._latest_contiguous_triplet(candidates)
            if triplet is None:
                continue

            if self._same_sign_segment_count_in_triplet_window(window, triplet) > int(self.params.max_same_sign_waves):
                continue
            if not self._wave_owns_adjacent_price_progression(window, triplet[1], "SHORT"):
                continue
            if not self._wave_owns_adjacent_price_progression(window, triplet[2], "SHORT"):
                continue
            if not self._top_triplet_structure_ok(triplet):
                continue
            if trigger_pivot is not None:
                trigger_price_ok, _ = self._top_trigger_price_ok(triplet, trigger_pivot)
                if not trigger_price_ok:
                    continue

            return triplet

        return None

    def _detect_bottom_triple_divergence(self) -> bool:
        if not self._is_first_shortening_bar(SegmentSign.NEGATIVE):
            return False

        waves = self._build_recent_waves()
        candidates = self._price_divergence_candidates(waves, SegmentSign.NEGATIVE)
        if not candidates:
            return False
        trigger_pivot = self._current_trigger_pivot(candidates[-1], SegmentSign.NEGATIVE)
        if trigger_pivot is None:
            return False
        triplet = self._find_bottom_triplet(waves, trigger_pivot)
        if triplet is None:
            return False
        if not self._latest_leg_trigger_strength_ok(triplet):
            return False

        r1, r2, r3 = triplet
        trigger_price_ok, trigger_price_extreme = self._bottom_trigger_price_ok(triplet, trigger_pivot)
        if not trigger_price_ok:
            return False
        structure_key = self._structure_key(r1, r2)
        if (
            self._last_long_structure_key == structure_key
            and self._last_long_price_extreme is not None
            and float(trigger_price_extreme) >= float(self._last_long_price_extreme) - self.params.price_eps
        ):
            return False
        if self._last_long_price_extreme is not None and self._last_long_structure_key != structure_key:
            self._last_long_price_extreme = None
            self._last_long_structure_key = None
        current_bar = self.bar_idx()
        if self._last_long_signal_bar_idx is not None and current_bar - self._last_long_signal_bar_idx <= 1:
            return False

        self._last_long_signal_bar_idx = current_bar
        self._last_long_structure_key = structure_key
        self._last_long_price_extreme = float(trigger_price_extreme)
        event = self._build_signal_event("LONG", waves, triplet, trigger_pivot)
        signal_id = self._store_signal_event(event)
        self._long_signal_meta = {
            "suggested_stop_price": float(r3.price_extreme),
            "signal_time": event["signal_time"],
            "signal_bar_index": current_bar,
            "signal_event_id": signal_id,
        }
        self.log_debug(
            f"三段底背离检测: R1({r1.start_idx}-{r1.end_idx}, M={r1.extreme_val:.6f}, P={r1.price_extreme:.2f}) "
            f"R2({r2.start_idx}-{r2.end_idx}, M={r2.extreme_val:.6f}, P={r2.price_extreme:.2f}) "
            f"R3({r3.start_idx}-{r3.end_idx}, M={r3.extreme_val:.6f}, P={r3.price_extreme:.2f}) "
            f"trigger({trigger_pivot.idx}, M={trigger_pivot.macd_val:.6f}, Pbar={trigger_pivot.price_val:.2f})"
        )
        return True

    def _detect_top_triple_divergence(self) -> bool:
        if not self._is_first_shortening_bar(SegmentSign.POSITIVE):
            return False

        waves = self._build_recent_waves()
        candidates = self._price_divergence_candidates(waves, SegmentSign.POSITIVE)
        if not candidates:
            return False
        trigger_pivot = self._current_trigger_pivot(candidates[-1], SegmentSign.POSITIVE)
        if trigger_pivot is None:
            return False
        triplet = self._find_top_triplet(waves, trigger_pivot)
        if triplet is None:
            return False
        if not self._latest_leg_trigger_strength_ok(triplet):
            return False

        g1, g2, g3 = triplet
        trigger_price_ok, trigger_price_extreme = self._top_trigger_price_ok(triplet, trigger_pivot)
        if not trigger_price_ok:
            return False
        structure_key = self._structure_key(g1, g2)
        if (
            self._last_short_structure_key == structure_key
            and self._last_short_price_extreme is not None
            and float(trigger_price_extreme) <= float(self._last_short_price_extreme) + self.params.price_eps
        ):
            return False
        if self._last_short_price_extreme is not None and self._last_short_structure_key != structure_key:
            self._last_short_price_extreme = None
            self._last_short_structure_key = None
        current_bar = self.bar_idx()
        if self._last_short_signal_bar_idx is not None and current_bar - self._last_short_signal_bar_idx <= 1:
            return False

        self._last_short_signal_bar_idx = current_bar
        self._last_short_structure_key = structure_key
        self._last_short_price_extreme = float(trigger_price_extreme)
        event = self._build_signal_event("SHORT", waves, triplet, trigger_pivot)
        signal_id = self._store_signal_event(event)
        self._short_signal_meta = {
            "suggested_stop_price": float(g3.price_extreme),
            "signal_time": event["signal_time"],
            "signal_bar_index": current_bar,
            "signal_event_id": signal_id,
        }
        self.log_debug(
            f"三段顶背离检测: G1({g1.start_idx}-{g1.end_idx}, M={g1.extreme_val:.6f}, H={g1.price_extreme:.2f}) "
            f"G2({g2.start_idx}-{g2.end_idx}, M={g2.extreme_val:.6f}, H={g2.price_extreme:.2f}) "
            f"G3({g3.start_idx}-{g3.end_idx}, M={g3.extreme_val:.6f}, H={g3.price_extreme:.2f}) "
            f"trigger({trigger_pivot.idx}, M={trigger_pivot.macd_val:.6f}, Pbar={trigger_pivot.price_val:.2f})"
        )
        return True

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

    def get_long_signal_context(self) -> dict:
        return dict(self._long_signal_meta or {})

    def get_short_signal_context(self) -> dict:
        return dict(self._short_signal_meta or {})

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

        if self._entry_signal_bar_idx is None or self.bar_idx() != self._entry_signal_bar_idx + 1:
            return False

        ctx = self._active_trade
        if ctx is not None and ctx.stop_price is not None:
            stop_price = float(ctx.stop_price)
            if self._entry_direction == "LONG" and float(self.data.low[0]) <= stop_price:
                return False
            if self._entry_direction == "SHORT" and float(self.data.high[0]) >= stop_price:
                return False

        hist_val = float(self.macd_hist[0])

        if not self._next_day_macd_follow_through_ok(self._entry_direction, self._entry_hist_val, hist_val):
            self.log_info(
                f"MACD止损触发({'多' if self._entry_direction == 'LONG' else '空'}): "
                f"entry_hist={self._entry_hist_val:.6f} current_hist={hist_val:.6f}"
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
                if self._pending_entry_hist_val is not None:
                    self._entry_hist_val = float(self._pending_entry_hist_val)
                else:
                    self._entry_hist_val = float(self.macd_hist[0])
                self._entry_direction = "LONG" if order.isbuy() else "SHORT"
                if self._pending_entry_signal_bar_idx is not None:
                    self._entry_signal_bar_idx = self._pending_entry_signal_bar_idx
                elif self._active_trade is not None:
                    signal_bar_index = (self._active_trade.signal_metadata or {}).get("signal_bar_index")
                    self._entry_signal_bar_idx = int(signal_bar_index) if signal_bar_index is not None else None
                self._pending_entry_signal_bar_idx = None
                self._pending_entry_hist_val = None
                if self._active_trade is not None:
                    signal_id = (self._active_trade.signal_metadata or {}).get("signal_event_id")
                    self._update_signal_outcome(
                        signal_id,
                        "entered",
                        trade_id=int(getattr(self._active_trade, "trade_id", 0)),
                        entry_price=round(float(order.executed.price), 2),
                        entry_time=self.cur_datetime().isoformat(),
                    )
                self.log_info(f"记录入场MACD柱: direction={self._entry_direction} hist={self._entry_hist_val:.6f}")
            elif role == "exit" or role == "stop" or role == "take_profit":
                # Clear entry tracking on exit
                self._entry_hist_val = None
                self._entry_direction = None
                self._entry_signal_bar_idx = None
                self._pending_entry_hist_val = None
        elif order.status in (order.Canceled, order.Margin, order.Rejected):
            role = getattr(order, "info", {}).get("chainer_role")
            if role == "entry":
                tradeid = getattr(order, "tradeid", None)
                ctx = self._trades_by_id.get(int(tradeid)) if tradeid is not None else None
                signal_id = (ctx.signal_metadata or {}).get("signal_event_id") if ctx is not None else None
                self._update_signal_outcome(
                    signal_id,
                    "entry_order_failed",
                    order_status=int(order.status),
                )
                self._pending_entry_signal_bar_idx = None
                self._pending_entry_hist_val = None

    def on_signal_lifecycle_event(self, event_type: str, direction: str, signal_context=None, **payload):
        meta = dict(signal_context or {})
        signal_id = meta.get("signal_event_id")

        if event_type == "entry_context_created":
            self._pending_entry_signal_bar_idx = int(meta.get("signal_bar_index", self.bar_idx()))
            self._pending_entry_hist_val = float(self.macd_hist[0])
            trade_context = payload.get("trade_context")
            if trade_context is not None and getattr(trade_context, "stop_price", None) is not None:
                self.log_info(f"策略上下文: 使用建议止损 stop_price={float(trade_context.stop_price):.6f}")
            return

        if event_type == "entry_context_cancelled":
            self._update_signal_outcome(signal_id, "entry_context_cancelled", reason=payload.get("reason"))
            return

        if event_type == "blocked":
            reason = payload.get("reason")
            if reason == "active_trade":
                self._update_signal_outcome(signal_id, "blocked_active_trade", active_trade=payload.get("active_trade"))
            elif reason == "equity":
                self._update_signal_outcome(signal_id, "blocked_equity")
            elif reason == "mode":
                self._update_signal_outcome(signal_id, "blocked_mode")
            else:
                self._update_signal_outcome(signal_id, "blocked", reason=reason)
            return

        if event_type == "exit_requested":
            self._update_signal_outcome(signal_id, "exit_requested", reason=payload.get("reason"))

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
                    self.exit_trade(
                        key_bar_index=self.bar_idx(),
                        need_confirm=False,
                        exit_reason_code="strategy_stop",
                        exit_reason_label="策略止损逻辑退出",
                        exit_reason_detail="MACD 三背离后续走势失效",
                    )
                except (ValueError, RuntimeError) as e:
                    self.log_debug(f"MACD stop loss exit_trade failed: {e}")
                    # Fallback to direct close
                    self.close()

        # Signal processing is handled by BaseStrategy._process_signals()
