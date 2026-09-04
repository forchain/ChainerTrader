"""
ChainerTrader Library for backtrader.

This is a backtrader implementation of the Pine Script library
`src/pine_scripts/libraries/chainer_trader.pine`.

It provides:
- ChainerTraderLib: Helper class that uses backtrader data/indicators
- Static methods: Pure calculation functions (breakeven, risk/reward)

Usage:
    # In strategy __init__:
    self.chainer = ChainerTraderLib(self.data, self.atr)
    
    # In strategy next():
    stop_price = self.chainer.stop_price(
        "LONG", entry_key_bar_index, stoploss_atr_mult=1.0
    )
    confirm_status = self.chainer.entry_confirm("LONG", entry_key_bar_index)
    be_price = ChainerTraderLib.breakeven_price(
        "LONG", entry_price, initial_stop, self.data.close[0]
    )
"""

import math
from typing import Optional

import backtrader as bt


class ChainerTraderLib:
    """
    ChainerTrader Library Helper.
    
    Provides methods that match Pine Script library functions.
    Uses backtrader data and indicators for easy migration from Pine Script.
    
    Args:
        data: backtrader data feed (must have high, low, close)
        atr: backtrader ATR indicator (period 14)
    """
    
    def __init__(self, data: bt.LineSeries, atr: bt.Indicator):
        self.data = data
        self.atr = atr
    
    @staticmethod
    def normalize_direction(direction: str) -> str:
        """
        Normalize direction string (matches Pine Script normalizeDirection).
        
        - Numeric string >0 -> LONG
        - String "SHORT" -> SHORT
        - Others -> LONG
        """
        raw = (direction or "").strip()
        upper = raw.upper()
        try:
            num = float(raw)
        except ValueError:
            num = None
        
        if num is not None:
            return "LONG" if num > 0 else "SHORT"
        return "SHORT" if upper == "SHORT" else "LONG"
    
    def key_levels_by_bar_index(self, key_bar_index: int) -> tuple[bool, int, float, float]:
        """
        Get key bar levels by bar index (matches Pine Script keyLevelsByBarIndex).
        
        Returns:
            (found, key_time, key_high, key_low)
        """
        current_idx = len(self.data) - 1
        
        if key_bar_index < 0 or key_bar_index > current_idx:
            return False, 0, float('nan'), float('nan')
        
        shift = key_bar_index - current_idx
        
        try:
            key_high = float(self.data.high[shift])
            key_low = float(self.data.low[shift])
            key_time = int(self.data.datetime[shift])
        except (IndexError, TypeError):
            return False, 0, float('nan'), float('nan')
        
        return True, key_time, key_high, key_low
    
    def stop_price(
        self,
        direction: str,
        key_bar_index: int,
        stoploss_atr_mult: float,
    ) -> Optional[float]:
        """
        Calculate stop price (matches Pine Script stopPrice).
        
        Args:
            direction: "LONG" or "SHORT"
            key_bar_index: Bar index of the key bar
            stoploss_atr_mult: ATR multiplier (0 = disabled)
        
        Returns:
            Stop price or None if key bar not found
        """
        dir_norm = self.normalize_direction(direction)
        found, _, key_high, key_low = self.key_levels_by_bar_index(key_bar_index)
        
        if not found:
            return None
        
        current_idx = len(self.data) - 1
        shift = key_bar_index - current_idx
        
        # Get ATR value at key bar
        try:
            atr_val = float(self.atr[shift]) if shift <= 0 else float(self.atr[0])
        except (IndexError, TypeError):
            atr_val = float('nan')
        
        if dir_norm == "LONG":
            if stoploss_atr_mult == 0.0 or math.isnan(atr_val):
                return key_low
            return key_low - stoploss_atr_mult * atr_val
        
        # SHORT
        if stoploss_atr_mult == 0.0 or math.isnan(atr_val):
            return key_high
        return key_high + stoploss_atr_mult * atr_val
    
    def entry_confirm(self, direction: str, key_bar_index: int) -> int:
        """
        Check entry confirmation (matches Pine Script entryConfirm).
        
        Returns:
            1  -> Confirmed
            0  -> Pending
            -1 -> Failed
        """
        dir_norm = self.normalize_direction(direction)
        found, _, key_high, key_low = self.key_levels_by_bar_index(key_bar_index)
        
        if not found:
            return 0
        
        close = float(self.data.close[0])
        
        if dir_norm == "LONG":
            if close > key_high:
                return 1
            elif close < key_low:
                return -1
        else:  # SHORT
            if close < key_low:
                return 1
            elif close > key_high:
                return -1
        
        return 0
    
    def exit_confirm(self, direction: str, key_bar_index: int) -> int:
        """
        Check exit confirmation (matches Pine Script exitConfirm).
        
        Returns:
            1  -> Confirmed
            0  -> Pending
            -1 -> Failed
        """
        dir_norm = self.normalize_direction(direction)
        found, _, key_high, key_low = self.key_levels_by_bar_index(key_bar_index)
        
        if not found:
            return 0
        
        close = float(self.data.close[0])
        
        if dir_norm == "LONG":
            if close < key_low:
                return 1
            elif close > key_high:
                return -1
        else:  # SHORT
            if close > key_high:
                return 1
            elif close < key_low:
                return -1
        
        return 0
    
    @staticmethod
    def breakeven_price(
        direction: str,
        entry_price: float,
        initial_stop: float,
        close: float,
    ) -> Optional[float]:
        """
        Calculate breakeven price (matches Pine Script breakevenPrice).
        
        - risk = dir == LONG ? (entry - initialStop) : (initialStop - entry)
        - profit = dir == LONG ? (close - entry) : (entry - close)
        - n = floor(profit / risk + 1e-10)
        - n <= 0 -> None
        - LONG: entry + (n - 1) * risk
        - SHORT: entry - (n - 1) * risk
        """
        dir_norm = ChainerTraderLib.normalize_direction(direction)
        
        if any(math.isnan(v) for v in (entry_price, initial_stop, close)):
            return None
        
        if dir_norm == "LONG":
            risk = entry_price - initial_stop
        else:
            risk = initial_stop - entry_price
        
        if risk <= 0:
            return None
        
        if dir_norm == "LONG":
            profit = close - entry_price
        else:
            profit = entry_price - close
        
        n_float = profit / risk
        n = math.floor(n_float + 1e-10)
        if n <= 0:
            return None
        
        if dir_norm == "LONG":
            return entry_price + (n - 1) * risk
        return entry_price - (n - 1) * risk
    
    @staticmethod
    def risk_reward_price(
        direction: str,
        entry_price: float,
        stop_price: float,
        risk_reward_ratio: float,
    ) -> Optional[float]:
        """
        Calculate risk/reward target price (matches Pine Script riskRewardPrice).
        """
        dir_norm = ChainerTraderLib.normalize_direction(direction)
        
        if risk_reward_ratio <= 0:
            return None
        
        if dir_norm == "LONG":
            risk = entry_price - stop_price
            if risk <= 0:
                return None
            return entry_price + risk_reward_ratio * risk
        
        # SHORT
        risk = stop_price - entry_price
        if risk <= 0:
            return None
        return entry_price - risk_reward_ratio * risk
    
    @staticmethod
    def stop_hit(
        direction: str,
        stop_price_val: Optional[float],
        low: float,
        high: float,
    ) -> bool:
        """
        Check if stop loss was hit (matches Pine Script stopHit).
        
        Uses low/high for real-time checking (not close).
        """
        if stop_price_val is None or math.isnan(stop_price_val):
            return False
        
        dir_norm = ChainerTraderLib.normalize_direction(direction)
        
        if dir_norm == "LONG":
            return low <= stop_price_val
        return high >= stop_price_val

