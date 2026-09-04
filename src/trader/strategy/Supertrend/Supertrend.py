from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt

from trader.strategy.base_strategy import BaseStrategy
from trader.utils.ma import MAType
from trader.indicators.qqe import QQECalc
from trader.indicators.super_trend import SuperTrend
from trader.indicators.trend_a import TrendIndicatorA

class SupertrendStrategy(BaseStrategy):
    params = (
        # QQE parameters
        ('rsi_length_primary', 6),
        ('rsi_smoothing_primary', 5),
        ('qqe_factor_primary', 3.0),
        ('rsi_length_secondary', 6),
        ('rsi_smoothing_secondary', 5),
        ('qqe_factor_secondary', 1.61),
        
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
        self.st = SuperTrend(self.data,
                             period=self.params.atrperiod,
                             multiplier=self.params.atrdist,
                             use_atr=True)

        self.qqe_p = QQECalc(self.data,
                             rsi_len=self.params.rsi_length_primary,
                             rsi_smooth=self.params.rsi_smoothing_primary,
                             qqe_factor=self.params.qqe_factor_primary)
        self.qqe_s = QQECalc(self.data,
                             rsi_len=self.params.rsi_length_secondary,
                             rsi_smooth=self.params.rsi_smoothing_secondary,
                             qqe_factor=self.params.qqe_factor_secondary)

        dev = self.qqe_p.trendline - 50
        self.bb_mid = bt.ind.SMA(dev, period=self.params.bollinger_length)
        self.bb_up = self.bb_mid + self.params.bollinger_multiplier * bt.ind.StdDev(dev, period=self.params.bollinger_length)
        self.bb_down = self.bb_mid - self.params.bollinger_multiplier * bt.ind.StdDev(dev, period=self.params.bollinger_length)

        sm_p = self.qqe_p.l.smoothed_rsi - 50
        sm_s = self.qqe_s.l.smoothed_rsi - 50

        self.buy_sig = bt.And(
            sm_s > self.params.qqe_factor_secondary,
            sm_p > self.bb_up
        )

        self.sell_sig = bt.And(
            sm_s < -self.params.qqe_factor_secondary,
            sm_p < self.bb_down
        )

        self.ind = TrendIndicatorA(
            self.datas[1],
            ma_type=self.params.ma_type,
            ma_period=self.params.ma_period,
            alma_offset=self.params.alma_offset,
            alma_sigma=self.params.alma_sigma
        )

        self.stopLossPoint=0
        self.params.stoploss = True

    def next(self):
        """Main strategy logic"""
        super().next()
        
        if self.order:
            return

        ha_trend = self.ind.trend[0]
        
        # Trading logic
        opt_buy = False
        opt_sell = False
        
        # Buy condition: Supertrend buy signal + QQE up + Heikin Ashi bullish
        if self.st.buy_signal[0] and self.buy_sig[0] and ha_trend > 0:
            opt_buy = True
        
        # Sell condition: Supertrend sell signal + QQE down + Heikin Ashi bearish
        if self.st.sell_signal[0] and self.sell_sig[0] and ha_trend < 0:
            opt_sell = True

        # Execute trades
        if not self.position:
            if opt_buy:
                self.log_info(f'买入信号 - 价格: {self.data.close[0]:.2f}')
                self.order = self.buy()
                self.update_stop_loss_point()
        else:
            if opt_sell:
                self.log_info(f'卖出信号 - 价格: {self.data.close[0]:.2f}')
                self.order = self.sell()

            elif self.need_stop_loss():
                self.log_info(f'止损触发 - 价格: {self.data.close[0]:.2f}')
                self.order = self.sell()
