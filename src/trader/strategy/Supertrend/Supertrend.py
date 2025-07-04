from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt
import numpy as np
from enum import Enum

from trader.strategy.base_strategy import BaseStrategy


class MAType(Enum):
    """Moving Average Types"""
    ALMA = 'ALMA'
    HMA = 'HMA'
    SMA = 'SMA'
    SWMA = 'SWMA'
    VWMA = 'VWMA'
    WMA = 'WMA'
    ZLEMA = 'ZLEMA'
    EMA = 'EMA'


class SupertrendStrategy(BaseStrategy):
    """
    Supertrend Strategy - Python implementation of Pine Script
    Combines Supertrend, QQE, and Heikin Ashi indicators for trend following
    """
    
    params = (
        ('name', 'Supertrend'),
        ('period', 12),
        
        # Supertrend parameters
        ('atr_period', 9),
        ('atr_multiplier', 3.9),
        ('change_atr_method', True),
        ('source_type', 'hl2'),  # 'hl2', 'close', 'high', 'low'
        
        # QQE parameters
        ('rsi_length_primary', 6),
        ('rsi_smoothing_primary', 5),
        ('qqe_factor_primary', 3.0),
        ('threshold_primary', 3.0),
        ('rsi_length_secondary', 6),
        ('rsi_smoothing_secondary', 5),
        ('qqe_factor_secondary', 1.61),
        ('threshold_secondary', 3.0),
        
        # Bollinger Bands parameters
        ('bollinger_length', 50),
        ('bollinger_multiplier', 0.35),
        
        # Heikin Ashi MA parameters
        ('ma_type', MAType.EMA),
        ('ma_period', 9),
        ('alma_offset', 0.85),
        ('alma_sigma', 6),
    )

    def __init__(self):
        super().__init__()
        
        # Initialize ATR
        if self.params.change_atr_method:
            self.atr = bt.indicators.ATR(self.data, period=self.params.atr_period)
        else:
            self.atr = bt.indicators.SimpleMovingAverage(
                bt.indicators.TrueRange(self.data), 
                period=self.params.atr_period
            )
        
        # Initialize Supertrend
        self.supertrend = self._calculate_supertrend()
        
        # Initialize QQE indicators
        self.primary_qqe, self.primary_rsi = self._calculate_qqe(
            self.params.rsi_length_primary,
            self.params.rsi_smoothing_primary,
            self.params.qqe_factor_primary
        )
        
        self.secondary_qqe, self.secondary_rsi = self._calculate_qqe(
            self.params.rsi_length_secondary,
            self.params.rsi_smoothing_secondary,
            self.params.qqe_factor_secondary
        )
        
        # Initialize Bollinger Bands
        self.bollinger_basis = bt.indicators.SimpleMovingAverage(
            self.primary_qqe - 50, 
            period=self.params.bollinger_length
        )
        self.bollinger_deviation = bt.indicators.StdDev(
            self.primary_qqe - 50, 
            period=self.params.bollinger_length
        ) * self.params.bollinger_multiplier
        self.bollinger_upper = self.bollinger_basis + self.bollinger_deviation
        self.bollinger_lower = self.bollinger_basis - self.bollinger_deviation
        
        # Initialize Heikin Ashi MA
        self.ha_ma = self._calculate_heikin_ashi_ma()
        
        # Trade management
        self.stop_loss_price = 0.0
        self.trend = 1  # 1 for uptrend, -1 for downtrend
        self.prev_trend = 1

    def _get_source(self):
        """Get price source based on configuration"""
        if self.params.source_type == 'hl2':
            return (self.data.high + self.data.low) / 2
        elif self.params.source_type == 'close':
            return self.data.close
        elif self.params.source_type == 'high':
            return self.data.high
        elif self.params.source_type == 'low':
            return self.data.low
        else:
            return (self.data.high + self.data.low) / 2

    def _calculate_supertrend(self):
        """Calculate Supertrend indicator"""
        src = self._get_source()
        
        # Calculate up and down bands
        up = src - self.params.atr_multiplier * self.atr
        dn = src + self.params.atr_multiplier * self.atr
        
        # Initialize arrays to store values
        up_vals = []
        dn_vals = []
        trend_vals = []
        
        for i in range(len(self.data)):
            if i == 0:
                up_vals.append(up[i])
                dn_vals.append(dn[i])
                trend_vals.append(1)
            else:
                # Update up band
                up1 = up_vals[i-1] if i > 0 else up[i]
                if self.data.close[i-1] > up1:
                    up_vals.append(max(up[i], up1))
                else:
                    up_vals.append(up[i])
                
                # Update down band
                dn1 = dn_vals[i-1] if i > 0 else dn[i]
                if self.data.close[i-1] < dn1:
                    dn_vals.append(min(dn[i], dn1))
                else:
                    dn_vals.append(dn[i])
                
                # Update trend
                prev_trend = trend_vals[i-1] if i > 0 else 1
                if prev_trend == -1 and self.data.close[i] > dn1:
                    trend_vals.append(1)
                elif prev_trend == 1 and self.data.close[i] < up1:
                    trend_vals.append(-1)
                else:
                    trend_vals.append(prev_trend)
        
        return trend_vals

    def _calculate_qqe(self, rsi_length, smoothing_factor, qqe_factor):
        """Calculate QQE indicator"""
        # Calculate RSI
        rsi = bt.indicators.RSI(self.data.close, period=rsi_length)
        
        # Calculate smoothed RSI
        smoothed_rsi = bt.indicators.ExponentialMovingAverage(rsi, period=smoothing_factor)
        
        # Calculate ATR of RSI
        wilders_length = rsi_length * 2 - 1
        atr_rsi = bt.indicators.ExponentialMovingAverage(
            bt.indicators.TrueRange(smoothed_rsi), 
            period=wilders_length
        )
        
        # Calculate dynamic ATR
        dynamic_atr_rsi = atr_rsi * qqe_factor
        
        # Initialize QQE trend line
        qqe_trend_line = []
        trend_direction = []
        
        for i in range(len(self.data)):
            if i == 0:
                qqe_trend_line.append(smoothed_rsi[i])
                trend_direction.append(1)
            else:
                atr_delta = dynamic_atr_rsi[i]
                new_short_band = smoothed_rsi[i] + atr_delta
                new_long_band = smoothed_rsi[i] - atr_delta
                
                prev_long_band = qqe_trend_line[i-1]
                prev_short_band = qqe_trend_line[i-1]
                
                # Update bands
                if (smoothed_rsi[i-1] > prev_long_band and 
                    smoothed_rsi[i] > prev_long_band):
                    long_band = max(prev_long_band, new_long_band)
                else:
                    long_band = new_long_band
                
                if (smoothed_rsi[i-1] < prev_short_band and 
                    smoothed_rsi[i] < prev_short_band):
                    short_band = min(prev_short_band, new_short_band)
                else:
                    short_band = new_short_band
                
                # Update trend direction
                prev_direction = trend_direction[i-1]
                if smoothed_rsi[i] > prev_short_band:
                    trend_direction.append(1)
                elif smoothed_rsi[i] < prev_long_band:
                    trend_direction.append(-1)
                else:
                    trend_direction.append(prev_direction)
                
                # Set QQE trend line
                if trend_direction[i] == 1:
                    qqe_trend_line.append(long_band)
                else:
                    qqe_trend_line.append(short_band)
        
        return qqe_trend_line, smoothed_rsi

    def _calculate_heikin_ashi_ma(self):
        """Calculate Heikin Ashi moving average"""
        # Calculate Heikin Ashi values
        ha_open = []
        ha_close = []
        ha_high = []
        ha_low = []
        
        for i in range(len(self.data)):
            if i == 0:
                ha_open.append(self.data.open[i])
                ha_close.append(self.data.close[i])
                ha_high.append(self.data.high[i])
                ha_low.append(self.data.low[i])
            else:
                ha_open.append((ha_open[i-1] + ha_close[i-1]) / 2)
                ha_close.append((self.data.open[i] + self.data.high[i] + 
                               self.data.low[i] + self.data.close[i]) / 4)
                ha_high.append(max(self.data.high[i], ha_open[i], ha_close[i]))
                ha_low.append(min(self.data.low[i], ha_open[i], ha_close[i]))
        
        # Calculate moving average based on type
        if self.params.ma_type == MAType.EMA:
            ma = bt.indicators.ExponentialMovingAverage(
                bt.LineSeries(ha_close), 
                period=self.params.ma_period
            )
        elif self.params.ma_type == MAType.SMA:
            ma = bt.indicators.SimpleMovingAverage(
                bt.LineSeries(ha_close), 
                period=self.params.ma_period
            )
        else:
            # Default to EMA
            ma = bt.indicators.ExponentialMovingAverage(
                bt.LineSeries(ha_close), 
                period=self.params.ma_period
            )
        
        return ma

    def _get_qqe_signals(self):
        """Get QQE buy/sell signals"""
        if len(self.data) < 1:
            return False, False
        
        # QQE up signal
        qqe_up = (self.secondary_rsi[0] - 50 > self.params.threshold_secondary and 
                 self.primary_rsi[0] - 50 > self.bollinger_upper[0])
        
        # QQE down signal
        qqe_down = (self.secondary_rsi[0] - 50 < -self.params.threshold_secondary and 
                   self.primary_rsi[0] - 50 < self.bollinger_lower[0])
        
        return qqe_up, qqe_down

    def _get_heikin_ashi_trend(self):
        """Get Heikin Ashi trend direction"""
        if len(self.data) < 1:
            return 0
        
        # Calculate trend based on Heikin Ashi MA
        ha_open = (self.data.open[0] + self.data.close[0]) / 2
        ha_close = (self.data.open[0] + self.data.high[0] + 
                   self.data.low[0] + self.data.close[0]) / 4
        
        if ha_close > ha_open:
            return 1  # Bullish
        else:
            return -1  # Bearish

    def next(self):
        """Main strategy logic"""
        super().next()
        
        if self.order:
            return
        
        # Update trend
        if len(self.data) > 0:
            self.prev_trend = self.trend
            self.trend = self.supertrend[-1] if len(self.supertrend) > 0 else 1
        
        # Get signals
        buy_signal = self.trend == 1 and self.prev_trend == -1
        sell_signal = self.trend == -1 and self.prev_trend == 1
        
        qqe_up, qqe_down = self._get_qqe_signals()
        ha_trend = self._get_heikin_ashi_trend()
        
        # Trading logic
        opt_buy = False
        opt_sell = False
        
        # Buy condition: Supertrend buy signal + QQE up + Heikin Ashi bullish
        if buy_signal and qqe_up and ha_trend > 0:
            opt_buy = True
        
        # Sell condition: Supertrend sell signal + QQE down + Heikin Ashi bearish
        if sell_signal and qqe_down and ha_trend < 0:
            opt_sell = True
        
        # Execute trades
        if not self.position:
            if opt_buy:
                self.log_info(f'买入信号 - 价格: {self.data.close[0]:.2f}')
                self.order = self.buy()
                self.stop_loss_price = self.data.low[0]  # Use Supertrend up band as stop loss
        else:
            if opt_sell:
                self.log_info(f'卖出信号 - 价格: {self.data.close[0]:.2f}')
                self.order = self.sell()
                self.stop_loss_price = 0.0
            elif self.need_stop_loss():
                self.log_info(f'止损触发 - 价格: {self.data.close[0]:.2f}')
                self.order = self.sell()
                self.stop_loss_price = 0.0

    def notify_order(self, order):
        """Handle order notifications"""
        super().notify_order(order)
        
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log_info(f'买入执行 - 价格: {order.executed.price:.2f}')
            else:
                self.log_info(f'卖出执行 - 价格: {order.executed.price:.2f}')

    def notify_trade(self, trade):
        """Handle trade notifications"""
        super().notify_trade(trade)
        
        if trade.isclosed:
            self.log_info(f'交易完成 - 毛利润: {trade.pnl:.2f}, 净利润: {trade.pnlcomm:.2f}')