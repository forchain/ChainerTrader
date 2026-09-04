import backtrader as bt

class SuperTrend(bt.Indicator):
    lines = ('supertrend', 'direction', 'up', 'down', 'buy_signal', 'sell_signal')
    params = (
        ('period', 10),
        ('multiplier', 3.0),
        ('use_atr', True),  # True: use ATR, False: use SMA of TR
    )

    def __init__(self):
        if self.p.use_atr:
            self.atr = bt.indicators.ATR(period=self.p.period)
        else:
            self.atr = bt.indicators.SMA(bt.indicators.TrueRange(), period=self.p.period)



    def next(self):
        hl2 = (self.data.high[0] + self.data.low[0]) / 2

        self.l.up[0] = hl2 - self.p.multiplier * self.atr[0]
        self.l.down[0] = hl2 + self.p.multiplier * self.atr[0]
        # Smoothing logic
        if self.data.close[-1] > self.l.up[-1]:
            if self.l.up[0]<self.l.up[-1]:
                self.l.up[0]=self.l.up[-1]

        if self.data.close[-1] < self.l.down[-1]:
            if self.l.down[0]>self.l.down[-1]:
                self.l.down[0]=self.l.down[-1]

        if self.data.close[0] > self.l.down[-1]:
            self.l.direction[0]=1
        else:
            if self.data.close[0] < self.l.up[-1]:
                self.l.direction[0] = -1
            else:
                self.l.direction[0] = self.l.direction[-1]

        # Supertrend value
        if self.l.direction[0] == 1:
            self.l.supertrend[0] = self.l.up[0]
        else:
            self.l.supertrend[0] = self.l.down[0]

        # Signal lines
        if self.l.direction[0] == 1 and self.l.direction[-1] == -1:
            self.l.buy_signal[0] = True

        if self.l.direction[0] == -1 and self.l.direction[-1] == 1:
            self.l.sell_signal[0] = True