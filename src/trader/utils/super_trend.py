import backtrader as bt

class SuperTrend(bt.Indicator):
    lines = ('supertrend', 'direction')
    params = dict(
        period=9,
        multiplier=3.9,
        change_atr=True
    )

    def __init__(self):
        hl2 = (self.data.high + self.data.low) / 2.0

        # ATR 选择：True ATR 或 SMA(TR)
        if self.p.change_atr:
            self.atr = bt.indicators.ATR(self.data, period=self.p.period)
        else:
            tr = bt.indicators.TrueRange(self.data)
            self.atr = bt.indicators.SimpleMovingAverage(tr, period=self.p.period)

        basic_ub = hl2 - (self.p.multiplier * self.atr)
        basic_lb = hl2 + (self.p.multiplier * self.atr)

        self.bub = basic_ub
        self.blb = basic_lb

        # 存储最终上下轨线
        self.ub = self.bub(-1)
        self.lb = self.blb(-1)

        # 初始化方向线
        self.l.direction = bt.LineNum(0)

    def next(self):
        prev_close = self.data.close[-1]
        curr_close = self.data.close[0]

        self.ub[0] = self.bub[0] if self.bub[0] < self.ub[-1] or prev_close > self.ub[-1] else self.ub[-1]
        self.lb[0] = self.blb[0] if self.blb[0] > self.lb[-1] or prev_close < self.lb[-1] else self.lb[-1]

        # 判断趋势方向切换
        prev_dir = self.l.direction[-1]
        curr_dir = prev_dir
        if prev_dir == -1 and curr_close > self.ub[-1]:
            curr_dir = 1
        elif prev_dir == 1 and curr_close < self.lb[-1]:
            curr_dir = -1

        self.l.direction[0] = curr_dir
        self.l.supertrend[0] = self.lb[0] if curr_dir == 1 else self.ub[0]