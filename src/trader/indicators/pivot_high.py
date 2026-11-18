import backtrader as bt

from trader.core.strategy.domain.indicators import is_pivot_high


class PivotHigh(bt.Indicator):
    lines = ("pivothigh",)
    params = (
        ("left", 3),
        ("right", 3),
    )
    plotinfo = dict(subplot=False)
    plotlines = dict(pivothigh=dict(marker="^", markersize=8.0, color="red", fillstyle="full"))

    def __init__(self):
        self.window_size = self.p.left + self.p.right + 1
        self.addminperiod(self.window_size)

    def next(self):
        self.lines.pivothigh[0] = float("nan")
        if len(self.data) <= self.window_size:
            return

        mid_idx = self.middle_idx()
        values = [self.data[i] for i in range(-self.p.left - self.p.right, 1)]

        if is_pivot_high(values, right=self.p.right):
            self.lines.pivothigh[mid_idx] = values[-1 + mid_idx]

    def middle_value(self):
        return self.lines.pivothigh[self.middle_idx()]

    def middle_idx(self):
        return -self.p.right
