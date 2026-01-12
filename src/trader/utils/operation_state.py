import backtrader as bt
from backtrader import num2date

from trader.utils.operate import Operate, OperateType


class OptStatAnalyzer(bt.Analyzer):
    params = (("si", None),)

    def __init__(self):
        self.buys = 0
        self.sells = 0
        self.longs = 0
        self.shorts = 0
        self.closes = 0
        self.opts: list[Operate] = []
        self.position_size = 0

    def notify_order(self, order):
        if order.status == order.Completed:
            prev_position = self.position_size
            order_size = order.executed.size
            
            if order.isbuy():
                self.buys += 1
                if prev_position == 0:
                    otype = OperateType.LONG
                    self.longs += 1
                elif prev_position < 0:
                    otype = OperateType.CLOSE
                    self.closes += 1
                else:
                    otype = OperateType.BUY
                self.position_size += order_size
            else:
                self.sells += 1
                if prev_position == 0:
                    otype = OperateType.SHORT
                    self.shorts += 1
                elif prev_position > 0:
                    otype = OperateType.CLOSE
                    self.closes += 1
                else:
                    otype = OperateType.SELL
                self.position_size -= order_size

            self.opts.append(
                Operate(
                    otype,
                    num2date(self.data.datetime[0]).timestamp(),
                    self.data.close[0],
                )
            )
        elif order.status == order.Submitted:
            if hasattr(self, 'strategy') and self.strategy:
                self.position_size = self.strategy.position.size

    def notify_trade(self, trade):
        if hasattr(self, 'strategy') and self.strategy:
            self.position_size = self.strategy.position.size
        elif trade.isclosed:
            self.position_size = 0
        else:
            if hasattr(trade, 'size'):
                self.position_size = trade.size

    def get_analysis(self):
        return {
            "buys": self.buys,
            "sells": self.sells,
            "longs": self.longs,
            "shorts": self.shorts,
            "closes": self.closes,
            "opts": self.opts,
        }
