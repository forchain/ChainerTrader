import backtrader as bt

class Abs(bt.Indicator):
    lines = ('out',)
    params = (('src', None),)
    def __init__(self):
        src = self.p.src
        # 在 __init__ 中声明，可用于其他指标链中
        self.l.out = abs(src - src(-1))

class QQECalc(bt.Indicator):
    lines = ('trendline', 'smoothed_rsi')
    params = dict(rsi_len=6, rsi_smooth=5, qqe_factor=3.0)

    def __init__(self):
        rsi = bt.ind.RSI(self.data, period=self.p.rsi_len)
        smoothed = bt.ind.EMA(rsi, period=self.p.rsi_smooth)

        wilders = self.p.rsi_len * 2 - 1
        abs_delta = Abs(src=smoothed)
        atr_rsi = bt.ind.EMA(abs_delta.out, period=wilders)
        dyn_atr = atr_rsi * self.p.qqe_factor

        lb = smoothed - dyn_atr
        ub = smoothed + dyn_atr

        cond = bt.And(smoothed(-1) > lb(-1), smoothed > lb(-1))
        lb_upd = bt.If(cond, bt.Max(lb(-1), lb), lb)

        cond2 = bt.And(smoothed(-1) < ub(-1), smoothed < ub(-1))
        ub_upd = bt.If(cond2, bt.Max(ub(-1), ub), ub)

        self.l.trendline = bt.If(bt.ind.CrossUp(smoothed, lb_upd(-1)), lb_upd,
                            bt.If(bt.ind.CrossDown(smoothed, ub_upd(-1)), ub_upd, lb_upd))
        self.l.smoothed_rsi = smoothed

