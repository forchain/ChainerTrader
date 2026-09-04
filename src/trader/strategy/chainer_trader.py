"""
ChainerTrader Strategy Template (v3)

A template strategy demonstrating the Chainer framework signal interface.
Uses MA Cross (Moving Average Crossover) as the example signal generator.

Signal Semantics (Fixed):
- Long Signal: Golden cross - fast SMA crosses above slow SMA (做多信号)
- Short Signal: Death cross - fast SMA crosses below slow SMA (做空信号)

Trading Modes:
- LONG_ONLY: Long signal opens long, short signal closes long
- SHORT_ONLY: Short signal opens short, long signal closes short
- BOTH: Long signal opens long, short signal opens short, exit via stop/breakeven/TP

This template can be used as a starting point for new strategies by:
1. Copying this file
2. Replacing get_long_signal() and get_short_signal() implementations
3. Adding any required indicators in __init__()
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import backtrader as bt

from trader.strategy.base_strategy import BaseStrategy


class ChainerTraderStrategy(BaseStrategy):
    """
    ChainerTrader template strategy using MA Cross signals.

    Demonstrates how to use the Chainer framework's signal interface
    by implementing get_long_signal() and get_short_signal() methods.
    """

    params = (
        ("name", "ChainerTrader"),
        # Signal parameters
        ("fast_length", 9),
        ("slow_length", 21),
        # Chainer Framework parameters
        ("chainer_mode", "LONG_ONLY"),  # LONG_ONLY, SHORT_ONLY, BOTH
        ("chainer_stoploss_atr_mult", 1.0),  # Stop loss ATR multiple (0 = disabled)
        ("chainer_trailing_stop_ratio", 0.0),  # Moving stop ratio (0 = disabled)
        ("chainer_need_confirm", True),  # Require confirmation for both entry and exit
        ("chainer_enable_breakeven", True),  # Enable breakeven
        ("chainer_risk_reward_ratio", 2.0),  # Risk/reward ratio (0 = disabled)
        # Disable new entries when equity falls below this percentage of initial account value (0 = disabled)
        ("chainer_min_equity_percent", 0.0),
    )

    def __init__(self):
        super().__init__()

        # Initialize MA indicators
        self.fast_sma = bt.indicators.SimpleMovingAverage(
            self.data.close,
            period=self.params.fast_length,
        )
        self.slow_sma = bt.indicators.SimpleMovingAverage(
            self.data.close,
            period=self.params.slow_length,
        )

        # Order tracking
        self.order = None
        
        # Log trading mode for verification
        self.log_info(f"ChainerTrader 初始化: chainer_mode={self.params.chainer_mode}")

    def get_long_signal(self) -> bool:
        """
        Generate long signal: Golden cross (fast SMA crosses above slow SMA).

        Signal semantics are fixed: this always represents the condition to go long.

        Returns:
            bool: True when fast SMA crosses above slow SMA.
        """
        # Need at least 2 bars to detect crossover
        if len(self) < 2:
            return False

        # Golden cross: fast was below or equal, now above
        return self.fast_sma[-1] <= self.slow_sma[-1] and self.fast_sma[0] > self.slow_sma[0]

    def get_short_signal(self) -> bool:
        """
        Generate short signal: Death cross (fast SMA crosses below slow SMA).

        Signal semantics are fixed: this always represents the condition to go short.

        Returns:
            bool: True when fast SMA crosses below slow SMA.
        """
        # Need at least 2 bars to detect crossover
        if len(self) < 2:
            return False

        # Death cross: fast was above or equal, now below
        return self.fast_sma[-1] >= self.slow_sma[-1] and self.fast_sma[0] < self.slow_sma[0]

    def next(self):
        """Main strategy logic executed on each bar."""
        super().next()

        # Skip if order is pending
        if self.order:
            return

        # Skip if not enough data for MA calculation
        if len(self) < self.params.slow_length:
            return

        # Signal processing is handled by BaseStrategy._process_signals()
