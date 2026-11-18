from __future__ import annotations

from typing import Any

from prettytable import PrettyTable

from trader.core.task.domain import rank_results


def render_statistics_table(bts_list: list[Any]) -> str:
    """Render ranked strategy execution results as an ASCII table."""
    ranked = rank_results(bts_list)
    table = PrettyTable()
    table.field_names = [
        "Index",
        "策略",
        "币种",
        "总收益率",
        "持有增长率",
        "持仓最大回撤",
        "持仓回撤时长",
        "波动率",
        "胜率",
        "平均盈亏比",
        "平均盈利",
        "平均亏损",
        "操作买卖数",
        "K线数",
    ]
    for index, bts in enumerate(ranked):
        table.add_row(
            [
                index,
                bts.strategy,
                bts.symbol_interval,
                format(bts.ts.tret.total_return_rate, ".2f") + "%",
                f"{bts.ts.tret.hold_rate:.2f}%",
                f"{bts.ts.tret.max_drawdown:.2f}%",
                f"{bts.ts.tret.max_drawdown_duration}",
                f"{bts.ts.tret.volatility:.2f}%",
                f"{bts.ts.tret.win_rate:.2f}%",
                f"{bts.ts.tret.plr:.2f}",
                f"{bts.ts.tret.avg_profit:.2f}",
                f"{bts.ts.tret.avg_loss:.2f}",
                f"{bts.ts.tret.buys}/{bts.ts.tret.sells}",
                bts.ts.tret.data_len,
            ]
        )
    return str(table)


def render_signal_table(signals: list[dict[str, Any]]) -> str:
    """Render scanner entry signals as an ASCII table."""
    table = PrettyTable()
    table.field_names = ["Signal Time (Local)", "Symbol", "Interval", "Strategy", "Side", "Price"]
    for signal in signals:
        table.add_row(
            [
                signal["signal_time"],
                signal["symbol"],
                signal["interval"],
                signal["strategy"],
                signal["side"],
                signal.get("price"),
            ]
        )
    return table.get_string()


def render_optimization_summary_table(ranking_items: list[dict[str, Any]], *, top: int = 20) -> str:
    """Render top optimization ranking rows as an ASCII table."""
    table = PrettyTable()
    table.field_names = ["Rank", "Symbol", "Interval", "Param ID", "Score", "Total Return%", "Excess%", "Max DD%", "Trades"]
    for rank, item in enumerate(ranking_items[: max(0, top)], start=1):
        table.add_row(
            [
                rank,
                item.get("symbol", ""),
                item.get("interval", ""),
                item.get("param_id", ""),
                f"{float(item.get('score', 0.0)):.2f}",
                f"{float(item.get('avg_total_return_pct', 0.0)):.2f}%",
                f"{float(item.get('avg_excess_return_pct', 0.0)):.2f}%",
                f"{float(item.get('avg_max_dd_pct', 0.0)):.2f}%",
                int(item.get("total_trades", 0)),
            ]
        )
    return table.get_string()
