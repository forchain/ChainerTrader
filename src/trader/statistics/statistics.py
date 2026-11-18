from logging import Logger
from typing import Any

from trader.adapters.inbound.cli.rendering import render_statistics_table
from trader.common.config import Config
from trader.common.message import Message
from trader.core.task.domain import bounded_results, collect_operates, rank_results
from trader.statistics.stat import BackTraderStat, TraderStat


class Statistics:
    def __init__(self, cfg: Config, log: Logger, db_manager: Any):
        self.log = log
        self.cfg = cfg
        self.db_manager = db_manager
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
            self.log.info(f"\n{render_statistics_table(self.bts_list)}")

    def get_operates(self, limit: int = 10):
        return collect_operates(self.bts_list, limit)
