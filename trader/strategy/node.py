from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os.path

from trader.binance.csvdata import BinanceCSVData
from trader.common import path

import backtrader as bt
import backtrader.analyzers as btanalyzers

from prettytable import PrettyTable

from trader.utils.profitlossratio import ProfitLossRatioAnalyzer
from trader.utils.trend import TrendType
from trader.utils.volatility import VolatilityAnalyzer
from trader.utils.winrate import WinRateAnalyzer

class Node:
    def __init__(self,strategy,plot=False, commission=0.001, atr=True,period=14,mode=TrendType.NORMAL,datafile="ETHUSDT-1h-202301-202401.csv"):
        self.plot=plot
        self.commission=commission
        self.atr=atr

        cerebro = bt.Cerebro()
        cerebro.addstrategy(strategy, atr=atr,mode=mode,period=period)
        cerebro.addanalyzer(btanalyzers.SharpeRatio, _name='sharpeRatio')
        cerebro.addanalyzer(btanalyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(VolatilityAnalyzer, _name="volatility", cerebro=cerebro)
        cerebro.addanalyzer(WinRateAnalyzer, _name="winRate")
        cerebro.addanalyzer(ProfitLossRatioAnalyzer, _name="profitLossRatio")
        self.cerebro=cerebro

        datapath = os.path.join(path.GetDatasDir(), datafile)

        data = BinanceCSVData(
            dataname=datapath,
            fromdate=datetime.datetime(2023, 1, 1),
            todate=datetime.datetime(2024, 1, 1),
        )

        cerebro.adddata(data)
        self.initialCash = 100000
        cerebro.broker.setcash(self.initialCash)

        cerebro.addsizer(bt.sizers.FixedSize, stake=10)

        cerebro.broker.setcommission(commission=commission)

    def start(self):
        rets = self.cerebro.run()
        ret = rets[0]

        finalFund = self.cerebro.broker.getvalue()
        sharpeRatio = ret.analyzers.sharpeRatio.get_analysis()
        totalReturnRate = (finalFund - self.initialCash) / self.initialCash * 100

        drawdown = ret.analyzers.drawdown.get_analysis()
        maxDrawdown = drawdown.max.drawdown
        maxDrawdownDuration = drawdown.max.len
        volatility = ret.analyzers.volatility.get_analysis()
        winRate = ret.analyzers.winRate.get_analysis()
        profitLossRatio = ret.analyzers.profitLossRatio.get_analysis()
        plr = profitLossRatio['profitLossRatio']
        avgProfit = profitLossRatio['avgProfit']
        avgLoss = profitLossRatio['avgLoss']

        if self.plot:
            self.cerebro.plot()

        # statistics
        table = PrettyTable()
        table.field_names = ["Name", "Value"]
        table.add_row(["手续费率", self.commission])
        table.add_row(["ATR", self.atr])
        table.add_row(["初始资金", format(self.initialCash, '.2f')])
        table.add_row(["最终资金", format(finalFund, '.2f')])
        table.add_row(["总收益率", format(totalReturnRate, '.2f') + "%"])
        if sharpeRatio['sharperatio']:
            table.add_row(["夏普比率", format(sharpeRatio['sharperatio'], '.2f')])
        table.add_row(["最大回撤:", (f"{maxDrawdown:.2f}%")])
        table.add_row(["回撤持续:", (f"{maxDrawdownDuration:.2f}")])
        table.add_row(["波动率:", (f"{volatility:.2f}%")])
        table.add_row(["胜率:", (f"{winRate:.2f}%")])
        table.add_row(["平均盈亏比:", (f"{plr:.2f}")])
        table.add_row(["平均盈利:", (f"{avgProfit:.2f}")])
        table.add_row(["平均亏损:", (f"{avgLoss:.2f}")])

        print("\n")
        print(table)