"""
ChainerTrader Strategy Template

A template strategy demonstrating the Chainer framework signal interface.
Uses MA Cross (Moving Average Crossover) as the example signal generator.

Entry/Exit Logic:
- Entry Signal (LONG): Golden cross - fast SMA crosses above slow SMA
- Exit Signal (LONG): Death cross - fast SMA crosses below slow SMA
- For SHORT direction, signals are swapped automatically by the framework

This template can be used as a starting point for new strategies by:
1. Copying this file
2. Replacing get_entry_signal() and get_exit_signal() implementations
3. Adding any required indicators in __init__()
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import backtrader as bt

from trader.strategy.base_strategy import BaseStrategy


class ChainerTraderStrategy(BaseStrategy):
    """
    ChainerTrader template strategy using MA Cross signals.

    Demonstrates how to use the Chainer framework's signal interface
    by implementing get_entry_signal() and get_exit_signal() methods.
    """

    params = (
        ("name", "ChainerTrader"),
        # Signal parameters
        ("fast_length", 9),
        ("slow_length", 21),
        # Chainer Framework parameters
        ("chainer_allow_short", True),
        ("chainer_direction", "LONG"),  # LONG or SHORT
        ("chainer_auto_signal", True),  # Enable auto signal processing via get_entry_signal/get_exit_signal
        ("chainer_stoploss_atr_mult", 1.0),  # Stop loss ATR multiple (0 = disabled)
        ("chainer_entry_need_confirm", True),  # Require entry confirmation
        ("chainer_exit_need_confirm", True),  # Require exit confirmation
        ("chainer_enable_breakeven", True),  # Enable breakeven
        ("chainer_risk_reward_ratio", 1.0),  # Risk/reward ratio (0 = disabled)
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

    def get_entry_signal(self) -> bool:
        """
        Generate entry signal: Golden cross (fast SMA crosses above slow SMA).

        Returns:
            bool: True when fast SMA crosses above slow SMA.
        """
        # Need at least 2 bars to detect crossover
        if len(self) < 2:
            return False

        # Golden cross: fast was below or equal, now above
        return self.fast_sma[-1] <= self.slow_sma[-1] and self.fast_sma[0] > self.slow_sma[0]

    def get_exit_signal(self) -> bool:
        """
        Generate exit signal: Death cross (fast SMA crosses below slow SMA).

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
        # when chainer_auto_signal is True

