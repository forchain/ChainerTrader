import backtrader as bt

from trader.core.strategy.domain.indicators import is_pivot_low


class PivotLow(bt.Indicator):
    lines = ("pivotlow",)
    params = (
        ("left", 3),
        ("right", 3),
    )
    plotinfo = dict(subplot=False)
    plotlines = dict(pivotlow=dict(marker="v", markersize=8.0, color="green", fillstyle="full"))

    def __init__(self):
        self.window_size = self.p.left + self.p.right + 1
        self.addminperiod(self.window_size)

    def next(self):
        self.lines.pivotlow[0] = float("nan")
        if len(self.data) <= self.window_size:
            return

        mid_idx = self.middle_idx()
        values = [self.data[i] for i in range(-self.p.left - self.p.right, 1)]

        if is_pivot_low(values, right=self.p.right):
            self.lines.pivotlow[mid_idx] = values[-1 + mid_idx]

    def middle_value(self):
        return self.lines.pivotlow[self.middle_idx()]

    def middle_idx(self):
        return -self.p.right
