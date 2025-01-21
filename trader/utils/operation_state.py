import backtrader as bt

class OptStatAnalyzer(bt.Analyzer):
    def __init__(self):
        self.buys = 0
        self.sells = 0

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.buys +=1
            else:
                self.sells += 1

    def notify_trade(self, trade):
        pass

    def get_analysis(self):
        return {"buys":self.buys,"sells":self.sells}