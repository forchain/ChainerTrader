import backtrader as bt

from trader.utils.ma import MAType

def get_ma(data, period, ma_type, alma_offset=0.85, alma_sigma=6):
    if ma_type == MAType.EMA:
        return bt.ind.EMA(data, period=period)
    elif ma_type == MAType.SMA:
        return bt.ind.SMA(data, period=period)
    elif ma_type == MAType.WMA:
        return bt.ind.WMA(data, period=period)
    elif ma_type == MAType.HMA:
        return bt.ind.HullMovingAverage(data, period=period)
    else:
        return bt.ind.EMA(data, period=period)

class TrendIndicatorA(bt.Indicator):
    lines = ('open_ma', 'close_ma', 'high_ma', 'low_ma', 'trend')
    params = dict(
        ma_type='EMA', ma_period=9,
        alma_offset=0.85, alma_sigma=6
    )
    plotinfo = dict(subplot=False)

    def __init__(self):
        ha = self.data  # 已是 Heikin-Ashi 数据
        self.lines.open_ma = get_ma(ha.open, self.p.ma_period, self.p.ma_type, self.p.alma_offset, self.p.alma_sigma)
        self.lines.close_ma = get_ma(ha.close, self.p.ma_period, self.p.ma_type, self.p.alma_offset, self.p.alma_sigma)
        self.lines.high_ma = get_ma(ha.high, self.p.ma_period, self.p.ma_type, self.p.alma_offset, self.p.alma_sigma)
        self.lines.low_ma = get_ma(ha.low, self.p.ma_period, self.p.ma_type, self.p.alma_offset, self.p.alma_sigma)

    def next(self):
        o = self.lines.open_ma[0]
        c = self.lines.close_ma[0]
        h = self.lines.high_ma[0]
        l = self.lines.low_ma[0]
        self.lines.trend[0] = 100 * (c - o) / (h - l) if (h - l) != 0 else 0