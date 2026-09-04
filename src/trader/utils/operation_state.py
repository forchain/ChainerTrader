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


class MaxDrawdownAnalyzer(bt.Analyzer):
    """
    增量计算资金曲线的最大回撤，内存占用极低。
    """

    def __init__(self):
        # 当前的高水位线及其时间
        self.peak_equity = 0.0
        self.peak_time = None

        # 记录全局最大回撤的信息
        self.max_dd = 0.0
        self.max_dd_start = None  # 峰值时间
        self.max_dd_end = None  # 谷值时间

    def start(self):
        # 初始化初始资金，避免第一根Bar之前没有基准
        self.peak_equity = self.strategy.broker.get_cash()

    def next(self):
        # 获取当前时间及账户总值
        # 注意：使用 self.strategy.datetime.datetime() 直接获取 datetime 对象，比 num2date 更方便
        current_time = self.strategy.datetime.datetime()
        current_equity = self.strategy.broker.getvalue()

        # 1. 这里的逻辑：如果不仅要防守，还要考虑到初始资金可能就是最高点的情况
        # 初始化 peak（如果是第一帧）
        if self.peak_time is None:
            self.peak_equity = current_equity
            self.peak_time = current_time

        # 2. 如果创新高（High Water Mark）
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
            self.peak_time = current_time
            # 创新高时，当前回撤为0，不需要更新 max_dd

        # 3. 如果未创新高，计算当前回撤
        else:
            # 防御性编程：防止除以0
            if self.peak_equity > 0:
                drawdown = (self.peak_equity - current_equity) / self.peak_equity * 100.0

                # 如果当前回撤大于历史最大回撤，更新记录
                if drawdown > self.max_dd:
                    self.max_dd = drawdown
                    self.max_dd_start = self.peak_time  # 回撤的起点是之前的最高点时刻
                    self.max_dd_end = current_time  # 回撤的终点是当前时刻（谷底）

    def get_analysis(self):
        return {
            "max_drawdown": self.max_dd,
            "start": self.max_dd_start,
            "end": self.max_dd_end,
        }
