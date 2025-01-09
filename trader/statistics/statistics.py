from logging import Logger

from prettytable import PrettyTable

from trader.common.common import sleep
from trader.common.message import Message
from trader.statistics.stat import BackTraderStat, TraderStat


class Statistics:
    def __init__(self,cfg,log:Logger):
        self.log = log
        self.cfg = cfg
        self.log.info(f"Init Statistics")
        self.bts_list=[]

    def handler(self,msg:Message):
        self.log.info(f"handle message:{msg.name()}")
        if isinstance(msg.data,BackTraderStat):
            self.bts_list.append(msg.data)
        if isinstance(msg.data,TraderStat):
            self.bts_list.append(msg.data)

    def report(self):
        if len(self.bts_list) > 0:
            self.log.info(f"Report BackTrader stats")
            if len(self.bts_list) > 1:
                self.bts_list.sort(key=lambda bts: bts.tret.total_return_rate)

            table = PrettyTable()
            table.field_names = ["Index","策略", "币种", "总收益率","最大回撤","回撤持续","波动率","胜率","平均盈亏比","平均盈利","平均亏损"]
            index = 0
            for bts in self.bts_list:
                table.add_row([index,
                               bts.strategy,
                               bts.symbol_interval,
                               format(bts.tret.total_return_rate, '.2f') + "%",
                               (f"{bts.tret.max_drawdown:.2f}%"),
                               (f"{bts.tret.max_drawdown_duration:.2f}"),
                               (f"{bts.tret.volatility:.2f}%"),
                               (f"{bts.tret.win_rate:.2f}%"),
                               (f"{bts.tret.plr:.2f}"),
                               (f"{bts.tret.avg_profit:.2f}"),
                               (f"{bts.tret.avg_loss:.2f}")])
                index+=1

            print("\n")
            print(table)