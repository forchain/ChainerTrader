import backtrader as bt

class ProfitLossRatioAnalyzer(bt.Analyzer):
    def __init__(self):
        self.profitTrades = []  # 存储盈利交易的 pnl
        self.lossTrades = []  # 存储亏损交易的 pnl

    def notify_trade(self, trade):
        # 检查交易是否关闭并统计盈亏
        if trade.isclosed:
            if trade.pnl > 0:
                self.profitTrades.append(trade.pnl)  # 盈利交易
            elif trade.pnl < 0:
                self.lossTrades.append(trade.pnl)  # 亏损交易

    def get_analysis(self):
        # 计算平均盈利和平均亏损
        avgProfit = sum(self.profitTrades) / len(self.profitTrades) if self.profitTrades else 0
        avgLoss = sum(self.lossTrades) / len(self.lossTrades) if self.lossTrades else 0

        # 计算盈亏比
        profitLossRatio = abs(avgProfit / avgLoss) if avgLoss != 0 else float('inf')

        return {'profitLossRatio': profitLossRatio, 'avgProfit': avgProfit, 'avgLoss': avgLoss}