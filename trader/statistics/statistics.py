from logging import Logger

from fastapi.openapi.models import Operation
from prettytable import PrettyTable

from trader.common.common import sleep
from trader.common.message import Message
from trader.statistics.stat import BackTraderStat, TraderStat
from trader.strategy.trader_result import TraderResult


class Statistics:
    def __init__(self,cfg,log:Logger):
        self.log = log
        self.cfg = cfg
        self.log.info(f"Init Statistics")
        self.bts_list=[]

    def handler(self,msg:Message):
        self.log.info(f"handle message:{msg.name()}")
        add=False
        if isinstance(msg.data,BackTraderStat):
            self.bts_list.append(msg.data)
            add=True
        if isinstance(msg.data,TraderStat):
            self.bts_list.append(msg.data)
            add=True

        if self.cfg.stat == 0:
            return
        elif self.cfg.stat > 0:
            if len(self.bts_list) > self.cfg.stat:
                if add and len(self.bts_list) > 1:
                    self.bts_list.sort(key=lambda bts: bts.tret.total_return_rate,reverse=True)
                    del_stat = self.bts_list.pop()
                    self.log.info(
                        f"Remove item form stat list:{del_stat.strategy} {del_stat.symbol_interval} {del_stat.tret.total_return_rate}")

    def report(self):
        if len(self.bts_list) > 0:
            self.log.info(f"Report BackTrader stats")
            if len(self.bts_list) > 1:
                self.bts_list.sort(key=lambda bts: bts.tret.total_return_rate,reverse=True)

            table = PrettyTable()
            table.field_names = ["Index","策略", "币种", "总收益率","最大回撤","回撤持续","波动率","胜率","平均盈亏比","平均盈利","平均亏损","操作买卖数"]
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
                               (f"{bts.tret.avg_loss:.2f}"),
                               (f"{bts.tret.buys}/{bts.tret.sells}")])
                index+=1

            print("\n")
            print(table)

    def get_operates(self,limit:int = 10):
        ret=[]
        if len(self.bts_list) <= 0:
            return ret

        for ts in self.bts_list:
            if len(ret) >= limit:
                break
            if ts.tret.operate is None:
                continue
            ret.append(ts.tret.operate.to_dict())
        return ret
