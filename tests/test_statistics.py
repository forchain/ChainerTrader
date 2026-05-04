from types import SimpleNamespace

from trader.common.config import Config
from trader.common.logger import Logger
from trader.common.message import new_stat_msg
from trader.statistics.stat import TraderStat
from trader.statistics.statistics import Statistics
from trader.utils.task_state import TaskState


def test_statistics_ignores_trader_stat_without_result_when_ranking_is_bounded():
    cfg = Config()
    cfg.stat = 1
    statistics = Statistics(cfg, Logger(cfg), db_manager=None)
    state = TaskState(1, "TRADER", "BTCUSDT-1m")
    stat = TraderStat("strategy", "BTCUSDT-1m", state)

    statistics.handler(new_stat_msg(stat, 1))

    assert statistics.bts_list == []


def test_statistics_keeps_and_sorts_stats_with_results():
    cfg = Config()
    cfg.stat = 1
    statistics = Statistics(cfg, Logger(cfg), db_manager=None)
    low = TraderStat("low", "BTCUSDT-1m", TaskState(1, "TRADER", "BTCUSDT-1m", tret=SimpleNamespace(total_return_rate=1.0)))
    high = TraderStat("high", "ETHUSDT-1m", TaskState(2, "TRADER", "ETHUSDT-1m", tret=SimpleNamespace(total_return_rate=2.0)))

    statistics.handler(new_stat_msg(low, 1))
    statistics.handler(new_stat_msg(high, 2))

    assert [stat.strategy for stat in statistics.bts_list] == ["high"]
