import backtrader as bt

class PivotHigh(bt.Indicator):
    lines = ('pivothigh',)
    params = (('left', 3), ('right', 3),)
    plotinfo = dict(subplot=False)
    plotlines = dict(
        pivothigh=dict(marker='^', markersize=8.0, color='red', fillstyle='full')
    )

    def __init__(self):
        self.window_size = self.p.left + self.p.right+1
        self.addminperiod(self.window_size)

    def next(self):

        if len(self.data) < self.window_size:
            self.lines.pivothigh[0] = float('nan')
            return

        mid_idx = self.middle_idx()
        mid_val = self.data[mid_idx]

        is_pivot = True
        for i in range(-self.p.left - self.p.right, 1):
            if i == mid_idx:
                continue
            if self.data[i] >= mid_val:
                is_pivot = False
                break

        if is_pivot:
            self.lines.pivothigh[mid_idx] = mid_val

    def middle_value(self):
        return self.lines.pivothigh[self.middle_idx()]

    def middle_idx(self):
        return -self.p.right