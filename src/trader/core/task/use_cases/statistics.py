from typing import Any

from trader.core.shared.config import Config
from trader.core.shared.interfaces import StatisticsTableRenderer
from trader.core.shared.messages import Message
from trader.core.task.domain import bounded_results, collect_operates, rank_results
from trader.core.task.stats import BackTraderStat, TraderStat


class Statistics:
    def __init__(self, cfg: Config, log: Any, db_manager: Any, table_renderer: StatisticsTableRenderer):
        self.log = log
        self.cfg = cfg
        self.db_manager = db_manager
        self.table_renderer = table_renderer
        self.log.info("Init Statistics")
        self.bts_list = []

    def handler(self, msg: Message):
        self.log.info(f"handle message:{msg.name()}")
        add = False

        if isinstance(msg.data, BackTraderStat):
            add = self._add_result_stat(msg.data)
        if isinstance(msg.data, TraderStat):
            add = self._add_result_stat(msg.data)

        if self.cfg.stat == 0:
            return
        elif self.cfg.stat > 0 and add:
            self.bts_list = bounded_results(self.bts_list, self.cfg.stat)

    def _add_result_stat(self, stat: BackTraderStat | TraderStat) -> bool:
        tret = getattr(getattr(stat, "ts", None), "tret", None)
        if tret is None:
            return False
        self.bts_list.append(stat)
        return True

    def report(self):
        if len(self.bts_list) > 0:
            self.log.info("Report BackTrader stats")
            self.bts_list = rank_results(self.bts_list)
            self.log.info(f"\n{self.table_renderer(self.bts_list)}")

    def get_operates(self, limit: int = 10):
        return collect_operates(self.bts_list, limit)
