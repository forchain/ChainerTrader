import backtrader as bt

class WinRateAnalyzer(bt.Analyzer):
    def __init__(self):
        self.totalTrades = 0
        self.winningTrades = 0

    def notify_trade(self, trade):
        # 检查交易是否关闭并统计盈亏
        if trade.isclosed:
            self.totalTrades += 1
            if trade.pnl > 0:
                self.winningTrades += 1

    def get_analysis(self):
        # 计算并返回胜率
        winRate = (self.winningTrades / self.totalTrades) * 100 if self.totalTrades > 0 else 0.0
        return winRate