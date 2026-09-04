#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import backtrader as bt

from trader.analyzers.backtest_report import BacktestReportAnalyzer
from trader.exchange.binance.csvdata import BinanceCSVData
from trader.strategy.macd_triple_divergence import MacdTripleDivergenceStrategy
from trader.utils.operation_state import MaxDrawdownAnalyzer


class SilentStrategy(MacdTripleDivergenceStrategy):
    def log_info(self, msg):
        pass

    def log_debug(self, msg):
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the MACD triple divergence strategy and emit a structured JSON report."
    )
    parser.add_argument(
        "--data",
        default="data/BTCUSDT-1d-20170101-20251231.csv",
        help="CSV dataset path relative to the repo root.",
    )
    parser.add_argument(
        "--cash",
        type=float,
        default=100000.0,
        help="Initial cash for the backtest.",
    )
    parser.add_argument(
        "--commission",
        type=float,
        default=0.001,
        help="Commission ratio passed to Backtrader.",
    )
    return parser.parse_args()


def add_standard_analyzers(cerebro: bt.Cerebro) -> None:
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.02)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade_analyzer")
    cerebro.addanalyzer(bt.analyzers.SQN, _name="sqn")
    cerebro.addanalyzer(MaxDrawdownAnalyzer, _name="maxdd_ex")
    cerebro.addanalyzer(
        BacktestReportAnalyzer,
        _name="backtest_report",
        strategy_name="macd_triple_divergence",
        symbol="BTCUSDT",
        interval="1d",
    )


def newest_report_path(reports_dir: Path) -> Path | None:
    candidates = sorted(reports_dir.glob("macd_triple_divergence_BTCUSDT_1d_*.json"))
    return candidates[-1] if candidates else None


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    data_path = (repo_root / args.data).resolve()
    reports_dir = repo_root / "reports"

    if not data_path.exists():
        raise FileNotFoundError(f"Dataset not found: {data_path}")

    before = newest_report_path(reports_dir)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(SilentStrategy)
    cerebro.adddata(BinanceCSVData(dataname=str(data_path)))
    add_standard_analyzers(cerebro)
    cerebro.broker.setcash(args.cash)
    cerebro.broker.setcommission(commission=args.commission)
    cerebro.run()

    after = newest_report_path(reports_dir)
    if after is None or after == before:
        print("Report generation finished, but no new report file was detected.")
        return 1

    print(after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
