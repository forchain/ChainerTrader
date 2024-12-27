from logging import Logger

from prettytable import PrettyTable

from trader.common.message import Message
from trader.statistics.stat import BackTraderStat


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

    def report(self):
        if len(self.bts_list) > 0:
            if len(self.bts_list) > 1:
                self.bts_list.sort(key=lambda bts: bts.total_return_rate)

            table = PrettyTable()
            table.field_names = ["Index","策略", "币种", "总收益率"]
            index = 0
            for bts in self.bts_list:
                table.add_row([index,bts.strategy,bts.symbol_interval, format(bts.total_return_rate, '.2f') + "%"])
                index+=1

            print("\n")
            print(table)