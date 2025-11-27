import backtrader as bt


class QQEBand(bt.Indicator):
    lines = ("qqe_trend_line", "smoothed_rsi", "long_band", "short_band", "trend_direction")
    params = dict(rsi_length=6, smoothing_factor=5, qqe_factor=3.0)

    def __init__(self):
        wilders_length = self.p.rsi_length * 2 - 1
        rsi = bt.ind.RSI(period=self.p.rsi_length)
        smoothed_rsi = bt.ind.EMA(rsi, period=self.p.smoothing_factor)

        abs_rsi = abs(self.l.smoothed_rsi(-1) - smoothed_rsi)
        smoothed_atr_rsi = bt.ind.EMA(abs_rsi, period=wilders_length)
        atr_delta = smoothed_atr_rsi * self.p.qqe_factor

        new_long_band = smoothed_rsi - atr_delta
        new_short_band = smoothed_rsi + atr_delta

        self.l.long_band = bt.If(
            bt.And(self.l.smoothed_rsi(-1) > self.l.long_band(-1), smoothed_rsi > self.l.long_band(-1)),
            bt.Max(self.l.long_band(-1), new_long_band), new_long_band)

        self.l.short_band = bt.If(
            bt.And(self.l.smoothed_rsi(-1) < self.l.short_band(-1), smoothed_rsi < self.l.short_band(-1)),
            bt.Min(self.l.short_band(-1), new_short_band), new_short_band)

        long_band_cross = bt.ind.CrossOver(self.l.long_band(-1), smoothed_rsi)

        self.l.trend_direction = bt.If(
            bt.ind.CrossOver(smoothed_rsi, self.l.short_band(-1)),
            1, bt.If(long_band_cross, -1, self.l.trend_direction(-1)))

        self.l.qqe_trend_line = bt.If(self.l.trend_direction == 1, self.l.long_band, self.l.short_band)
        self.l.smoothed_rsi = smoothed_rsi


class QQEMod(bt.Indicator):
    lines = ("secondary_qqe_trend_line", "secondary_rsi_histogram", "qqe_up_signal", "qqe_down_signal")
    params = dict(rsi_length_primary=6, rsi_smoothing_primary=5, qqe_factor_primary=3.0, threshold_primary=3.0,
                  rsi_length_secondary=6, rsi_smoothing_secondary=5, qqe_factor_secondary=1.61, threshold_secondary=3.0,
                  bollinger_length=50, bollinger_multiplier=0.35)

    def __init__(self):
        p_qqe = QQEBand(rsi_length=self.p.rsi_length_primary, smoothing_factor=self.p.rsi_smoothing_primary,
                        qqe_factor=self.p.qqe_factor_primary)
        s_qqe = QQEBand(rsi_length=self.p.rsi_length_secondary, smoothing_factor=self.p.rsi_smoothing_secondary,
                        qqe_factor=self.p.qqe_factor_secondary)

        primary_qqe_trend_line = p_qqe.l.qqe_trend_line
        primary_rsi = p_qqe.l.smoothed_rsi

        secondary_qqe_trend_line = s_qqe.l.qqe_trend_line
        secondary_rsi = s_qqe.l.smoothed_rsi

        bollinger_basis = bt.ind.SMA(primary_qqe_trend_line - 50, period=self.p.bollinger_length)
        bollinger_deviation = bt.ind.StdDev(primary_qqe_trend_line - 50,
                                            period=self.p.bollinger_length) * self.p.bollinger_multiplier
        bollinger_upper = bollinger_basis + bollinger_deviation
        bollinger_lower = bollinger_basis - bollinger_deviation

        self.l.secondary_qqe_trend_line = secondary_qqe_trend_line - 50
        self.l.secondary_rsi_histogram = secondary_rsi - 50

        self.l.qqe_up_signal = bt.And(secondary_rsi - 50 > self.p.threshold_secondary,
                                      bt.If(primary_rsi - 50 > bollinger_upper, secondary_rsi - 50, bt.NAN))
        self.l.qqe_down_signal = bt.And(secondary_rsi - 50 > -self.p.threshold_secondary,
                                        bt.If(primary_rsi - 50 > bollinger_lower, secondary_rsi - 50, bt.NAN))
