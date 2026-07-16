from __future__ import annotations

import asyncio
import copy
import json
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from dotenv import load_dotenv

from trader.common.config import TRADER_DB, TRADER_EXCHANGE, TRADER_WARMUP_CANDLES, Config
from trader.common.logger import Logger
from trader.database.manager import DatabaseManager
from trader.exchange.binance.exchange import BinanceExchange
from trader.exchange.exchange_config import parse_exchange_config
from trader.task.backtrader_task import (
    BacktestSampleResult,
    backtest_data_start_time,
    build_backtest_sample_spec,
    run_backtest_sample,
)
from trader.task.dataset_resolver import DatasetResolver
from trader.task.optimization_report import write_optimization_artifacts
from trader.task.task_config import parse_task_config
from trader.task.task_type import TaskType
from trader.tools.auto_coin_selection import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_RANK_FIELD,
    load_auto_selection_task,
    select_top_symbols,
    write_json,
)

MONTH_STARTS = tuple(range(1, 13))
DEFAULT_REPORT_ID = "cmc100-binance-usdt-rolling-2025"
DEFAULT_YEAR = 2025


@dataclass(frozen=True)
class MonthWindow:
    month: str
    selection_start: str
    selection_end: str
    hold_start: str
    hold_end: str


@dataclass(frozen=True)
class SymbolRunResult:
    symbol: str
    ok: bool
    selection_return_pct: float | None
    hold_return_pct: float | None
    report_path: str | None
    error: str | None = None
    param_id: str | None = None
    params: dict[str, Any] | None = None


def _dt(year: int, month: int, day: int = 1) -> datetime:
    return datetime(year, month, day, 0, 0, 0)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _shift_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return datetime(year, month, value.day, value.hour, value.minute, value.second)


def monthly_windows(year: int) -> list[MonthWindow]:
    windows: list[MonthWindow] = []
    for month in MONTH_STARTS:
        current = year, month
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        selection_start = _fmt(_shift_months(_dt(year, month), -12))
        selection_end = _dt(current[0], current[1])
        hold_start = _dt(current[0], current[1])
        hold_end = _dt(next_year, next_month)
        windows.append(
            MonthWindow(
                month=f"{year}-{month:02d}",
                selection_start=selection_start,
                selection_end=_fmt(selection_end),
                hold_start=_fmt(hold_start),
                hold_end=_fmt(hold_end),
            )
        )
    return windows


def _build_task_definition(
    template: dict[str, Any],
    symbol: str,
    interval: str,
    start_time: str,
    end_time: str,
    optimization_run_id: str,
) -> dict[str, Any]:
    task = copy.deepcopy(template)
    task.pop("symbols", None)
    task["task_type"] = TaskType.BACK_TRADER.name
    task["symbol"] = symbol
    task["interval"] = interval
    task["start_time"] = start_time
    task["end_time"] = end_time
    task["optimization_run_id"] = optimization_run_id
    return task


def _task_config_for_run(
    template: dict[str, Any],
    symbol: str,
    interval: str,
    start_time: str,
    end_time: str,
    optimization_run_id: str,
):
    task_definition = _build_task_definition(template, symbol, interval, start_time, end_time, optimization_run_id)
    parsed = parse_task_config(json.dumps([task_definition]))
    if len(parsed) != 1:
        raise ValueError(f"expected one task config, got {len(parsed)}")
    return parsed[0]


def _selection_payload(run_results: list[SymbolRunResult]) -> list[dict[str, Any]]:
    items = []
    for result in run_results:
        if not result.ok or result.selection_return_pct is None:
            continue
        items.append(
            {
                "symbol": result.symbol,
                "interval": "1h",
                "param_id": result.param_id,
                "params": result.params or {},
                "avg_total_return_pct": result.selection_return_pct,
                "summary": {
                    "total_return_pct": result.selection_return_pct,
                    "avg_total_return_pct": result.selection_return_pct,
                },
            }
        )
    return items


def _summary_return_pct(run_results: list[SymbolRunResult]) -> float | None:
    returns = [result.hold_return_pct for result in run_results if result.ok and result.hold_return_pct is not None]
    if not returns:
        return None
    return round(mean(returns), 4)


def _compounded_return_pct(monthly_returns: list[float]) -> float:
    equity = 1.0
    for value in monthly_returns:
        equity *= 1.0 + value / 100.0
    return round((equity - 1.0) * 100.0, 4)


async def _build_context():
    load_dotenv(Path(".env"))

    db_url = os.environ.get(TRADER_DB)
    exchange_payload = os.environ.get(TRADER_EXCHANGE)
    warmup_candles = int(os.environ.get(TRADER_WARMUP_CANDLES, 500) or 500)

    if not db_url:
        raise RuntimeError("TRADER_DB is required for rolling backtests")
    if not exchange_payload:
        raise RuntimeError("TRADER_EXCHANGE is required for rolling backtests")

    cfg = Config(
        db=db_url,
        exchange=exchange_payload,
        warmup_candles=warmup_candles,
        log_level="ERROR",
        cash=100000.0,
        window=1000,
    )
    log = Logger(cfg, 10000, True)
    db_manager = DatabaseManager(cfg, log)
    await db_manager.start()
    exchange_cfg = parse_exchange_config(exchange_payload)
    if exchange_cfg is None:
        raise RuntimeError("failed to parse TRADER_EXCHANGE")
    exchange = BinanceExchange(exchange_cfg, log)
    return cfg, log, db_manager, exchange


async def _run_symbol_backtest(
    cfg: Config,
    resolver: DatasetResolver,
    process_pool: ProcessPoolExecutor,
    template: dict[str, Any],
    symbol: str,
    start_time: str,
    end_time: str,
    optimization_run_id: str,
):
    interval = template.get("interval", "1h")
    cfg_obj = _task_config_for_run(
        template,
        symbol,
        interval,
        start_time,
        end_time,
        optimization_run_id,
    )
    data_start_time = backtest_data_start_time(cfg, cfg_obj)
    prepare_result = await resolver.prepare(
        cfg_obj.symbol_interval,
        data_start_time,
        cfg_obj.end_time,
        allow_download=True,
    )
    if not prepare_result.ok:
        return cfg_obj, BacktestSampleResult(
            ok=False,
            task_id=cfg_obj.id,
            trader_result=None,
            logs=[],
            report=None,
            report_path=None,
            error=prepare_result.failure.message if prepare_result.failure else "dataset preparation failed",
        )
    spec = build_backtest_sample_spec(cfg, cfg_obj)
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(process_pool, run_backtest_sample, spec)
    return cfg_obj, result


async def run_rolling_evaluation(
    *,
    year: int = DEFAULT_YEAR,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    output_dir: str | Path | None = None,
    report_id: str = DEFAULT_REPORT_ID,
) -> dict[str, Any]:
    cfg, log, db_manager, exchange = await _build_context()
    try:
        resolver = DatasetResolver(db_manager, exchange, log)
        config = load_auto_selection_task(config_path)
        template = config["template"]["task"]
        windows = monthly_windows(year)
        universe_path = Path(config["universe"])
        universe_payload = json.loads(universe_path.read_text(encoding="utf-8"))
        universe = sorted(
            {
                item.get("symbol")
                for item in universe_payload.get("pairs", [])
                if item.get("symbol") and item.get("quote_asset") == "USDT"
            }
        )

        report_root = Path(output_dir) if output_dir is not None else Path.cwd() / "reports" / "optimizations" / report_id
        report_root.mkdir(parents=True, exist_ok=True)

        month_items: list[dict[str, Any]] = []
        monthly_returns: list[float] = []
        max_workers = max(1, min(4, os.cpu_count() or 1))
        with ProcessPoolExecutor(max_workers=max_workers) as process_pool:
            for window in windows:
                selection_results: list[SymbolRunResult] = []
                selection_reports: list[dict[str, Any]] = []
                selection_failures: list[dict[str, Any]] = []

                for symbol in universe:
                    cfg_obj, selection_run = await _run_symbol_backtest(
                        cfg,
                        resolver,
                        process_pool,
                        template,
                        symbol,
                        window.selection_start,
                        window.selection_end,
                        f"{report_id}-{window.month}-select",
                    )
                    if selection_run.ok and selection_run.report:
                        selection_results.append(
                            SymbolRunResult(
                                symbol=symbol,
                                ok=True,
                                selection_return_pct=float(selection_run.report.get("summary", {}).get("total_return_pct", 0.0)),
                                hold_return_pct=None,
                                report_path=selection_run.report_path,
                                param_id=cfg_obj.param_id,
                                params=dict(cfg_obj.strategy_params or {}),
                            )
                        )
                        selection_reports.append(selection_run.report)
                    else:
                        selection_failures.append(
                            {
                                "symbol": symbol,
                                "reason": "selection_failed",
                                "message": selection_run.error,
                            }
                        )

                ranking_payload = _selection_payload(selection_results)
                top_candidates = select_top_symbols(ranking_payload, top=10, rank_field=DEFAULT_RANK_FIELD)
                selected_symbols = [item["symbol"] for item in top_candidates]

                hold_results: list[SymbolRunResult] = []
                for symbol in selected_symbols:
                    cfg_obj, hold_run = await _run_symbol_backtest(
                        cfg,
                        resolver,
                        process_pool,
                        template,
                        symbol,
                        window.hold_start,
                        window.hold_end,
                        f"{report_id}-{window.month}-hold",
                    )
                    if hold_run.ok and hold_run.report:
                        hold_results.append(
                            SymbolRunResult(
                                symbol=symbol,
                                ok=True,
                                selection_return_pct=None,
                                hold_return_pct=float(hold_run.report.get("summary", {}).get("total_return_pct", 0.0)),
                                report_path=hold_run.report_path,
                                param_id=cfg_obj.param_id,
                                params=dict(cfg_obj.strategy_params or {}),
                            )
                        )
                    else:
                        selection_failures.append(
                            {
                                "symbol": symbol,
                                "reason": "hold_failed",
                                "message": hold_run.error,
                            }
                        )

                monthly_return_pct = _summary_return_pct(hold_results)
                if monthly_return_pct is None:
                    monthly_return_pct = 0.0
                monthly_returns.append(monthly_return_pct)

                month_items.append(
                    {
                        "month": window.month,
                        "selection_window": {
                            "start": window.selection_start,
                            "end": window.selection_end,
                        },
                        "hold_window": {
                            "start": window.hold_start,
                            "end": window.hold_end,
                        },
                        "eligible_symbols": len(selection_results),
                        "selected_symbols": selected_symbols,
                        "monthly_return_pct": round(monthly_return_pct, 4),
                        "cumulative_return_pct": _compounded_return_pct(monthly_returns),
                        "selected_runs": [asdict(item) for item in hold_results],
                        "selection_failures": selection_failures,
                    }
                )

                write_optimization_artifacts(
                    Path.cwd(),
                    f"{report_id}-{window.month}-selection",
                    selection_reports,
                    selection_failures,
                )

        result = {
            "report_id": report_id,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "year": year,
            "monthly": month_items,
            "final_return_pct": _compounded_return_pct(monthly_returns),
            "monthly_returns_pct": monthly_returns,
            "methodology": {
                "selection_metric": "avg_total_return_pct",
                "selection_top_n": 10,
                "selection_window": "previous 12 calendar months",
                "holding_window": "current calendar month",
                "return_aggregation": "equal_weight_mean_return_pct",
                "compound_method": "monthly_compound_growth",
                "universe_source": config_path,
                "warmup_candles": cfg.warmup_candles,
            },
            "universe_size": len(universe),
        }
        write_json(report_root / "summary.json", result)
        write_json(report_root / "monthly.json", month_items)
        return result
    finally:
        await db_manager.stop()


def main() -> int:
    result = asyncio.run(run_rolling_evaluation())
    report_root = Path.cwd() / "reports" / "optimizations" / DEFAULT_REPORT_ID
    print(report_root / "summary.json")
    print(json.dumps({"final_return_pct": result["final_return_pct"], "monthly_returns_pct": result["monthly_returns_pct"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
