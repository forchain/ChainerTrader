from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import logging
import os.path

from backtrader import num2date

from trader.binance.csvdata import BinanceCSVData
from trader.common import path

import backtrader as bt
import backtrader.analyzers as btanalyzers

from prettytable import PrettyTable

from trader.common.config import Config
from trader.strategy.trader_result import TraderResult
from trader.utils.operation_state import OptStatAnalyzer
from trader.utils.profitlossratio import ProfitLossRatioAnalyzer
from trader.utils.trend import TrendType
from trader.utils.volatility import VolatilityAnalyzer
from trader.utils.winrate import WinRateAnalyzer

class Node:
    def __init__(self,name,strategy,cfg:Config=None,log:logging.Logger=None,data=None):
        self.log=log
        self.name=name
        self.cfg=cfg

        log.info(f"New node")

        cerebro = bt.Cerebro()
        cerebro.addstrategy(strategy, atr=cfg.atr,mode=cfg.mode,period=cfg.period,log=log)
        cerebro.addanalyzer(btanalyzers.SharpeRatio, _name='sharpeRatio')
        cerebro.addanalyzer(btanalyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(VolatilityAnalyzer, _name="volatility", cerebro=cerebro)
        cerebro.addanalyzer(WinRateAnalyzer, _name="winRate")
        cerebro.addanalyzer(ProfitLossRatioAnalyzer, _name="profitLossRatio")
        cerebro.addanalyzer(OptStatAnalyzer, _name="optstat")
        self.cerebro=cerebro

        cerebro.adddata(data)
        cerebro.broker.setcash(cfg.cash)

        cerebro.addsizer(bt.sizers.FixedSize, stake=10)

        cerebro.broker.setcommission(commission=cfg.commission)

    def start(self):
        self.log.info(f"start node")

        rets = self.cerebro.run()
        ret = rets[0]

        finalFund = self.cerebro.broker.getvalue()
        sharpeRatio = ret.analyzers.sharpeRatio.get_analysis()
        totalReturnRate = (finalFund - self.cfg.cash) / self.cfg.cash * 100

        drawdown = ret.analyzers.drawdown.get_analysis()
        maxDrawdown = drawdown.max.drawdown
        maxDrawdownDuration = drawdown.max.len
        volatility = ret.analyzers.volatility.get_analysis()
        winRate = ret.analyzers.winRate.get_analysis()
        profitLossRatio = ret.analyzers.profitLossRatio.get_analysis()
        plr = profitLossRatio['profitLossRatio']
        avgProfit = profitLossRatio['avgProfit']
        avgLoss = profitLossRatio['avgLoss']

        optstat = ret.analyzers.optstat.get_analysis()

        if self.cfg.plot:
            self.cerebro.plot()

        data_len = len(self.cerebro.datas[0])
        end_time = num2date(self.cerebro.datas[0].datetime[0])
        start_time = num2date(self.cerebro.datas[0].datetime[1 - data_len])
        # statistics
        table = PrettyTable()
        table.field_names = ["Name", "Value"]
        table.add_row(["策略", f"{self.name}"])
        table.add_row(["手续费率", self.cfg.commission])
        table.add_row(["ATR", self.cfg.atr])
        table.add_row(["初始资金", format(self.cfg.cash, '.2f')])
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
        table.add_row(["开始时间", (f"{start_time}")])
        table.add_row(["结束时间", (f"{end_time}")])
        table.add_row(["数据量", data_len])
        table.add_row(["操作买单数", optstat['buys']])
        table.add_row(["操作卖单数", optstat['sells']])

        print("\n")
        print(table)

        return TraderResult(totalReturnRate,
                            maxDrawdown,
                            maxDrawdownDuration,
                            volatility,
                            winRate,
                            plr,
                            avgProfit,
                            avgLoss,
                            optstat['buys'],
                            optstat['sells'],
                            optstat['latest'])
