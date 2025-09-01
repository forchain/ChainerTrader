import backtrader as bt
from backtrader import num2date

from trader.utils.operate import Operate, OperateType


class OptStatAnalyzer(bt.Analyzer):
    params = (("si", None),)

    def __init__(self):
        self.buys = 0
        self.sells = 0
        self.opts:list[Operate] = []

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.buys += 1
                otype = OperateType.BUY
            else:
                self.sells += 1
                otype = OperateType.SELL

            self.opts.append(Operate(
                otype,
                num2date(self.data.datetime[0]).timestamp(),
                self.data.close[0],
            ))

    def notify_trade(self, trade):
        pass

    def get_analysis(self):
        return {"buys": self.buys, "sells": self.sells, "opts": self.opts}
