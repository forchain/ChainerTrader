from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from trader.core.optimization.domain import (
    DEFAULT_RANK_FIELD,
    CandidateSymbolSet,
    MonthWindow,
    SymbolRunResult,
    TaskTemplate,
    build_binance_usdt_pairs,
    build_cmc_binance_universe,
    build_cmc_constituents,
    build_selection_payload,
    compounded_return_pct,
    merge_auto_selection_config,
    monthly_windows,
    parse_auto_selection_task,
    render_optimization_tasks,
    render_top_symbol_tasks,
    select_top_symbols,
    summary_return_pct,
)
from trader.core.optimization.interfaces import (
    BacktestRunner,
    CandidateSymbolSource,
    RankingReportStore,
    TaskConfigFileStore,
)


class AutoCoinSelectionUseCase:
    """Coordinate market universe refresh, backtest task generation, and top-symbol task rendering."""

    def __init__(
        self,
        *,
        config_store: TaskConfigFileStore,
        symbol_source: CandidateSymbolSource | None = None,
    ):
        self.config_store = config_store
        self.symbol_source = symbol_source

    def execute(
        self,
        *,
        config_path: str,
        overrides: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        raw = self.config_store.load_json(config_path)
        config = merge_auto_selection_config(parse_auto_selection_task(raw), overrides or {})
        generated_at = now or datetime.now().astimezone()

        if self.symbol_source is not None:
            refresh = bool(config.get("refresh_market_data", False))
            if refresh or not self.config_store.exists(config["binance_pairs"]):
                exchange_info = self.symbol_source.fetch_binance_exchange_info()
                self.config_store.write_json(config["binance_pairs"], build_binance_usdt_pairs(exchange_info, generated_at))
            if refresh or not self.config_store.exists(config["constituents"]):
                cmc_payload = self.symbol_source.fetch_cmc_index(config["index"])
                self.config_store.write_json(
                    config["constituents"],
                    build_cmc_constituents(cmc_payload, generated_at, config["index"]),
                )

        universe_payload = build_cmc_binance_universe(
            self.config_store.load_json(config["constituents"]),
            self.config_store.load_json(config["binance_pairs"]),
            index=config["index"],
            constituents_path=str(config["constituents"]),
        )
        self.config_store.write_json(config["universe"], universe_payload)

        candidate_set = CandidateSymbolSet.from_universe_payload(self.config_store.load_json(config["universe"]))
        template = TaskTemplate(task=config["template"]["task"])

        if config.get("output"):
            all_tasks = render_optimization_tasks(
                template.as_dict(),
                candidate_set.symbols,
                config["profiles"],
                now=now,
            )
            if config.get("optimization_run_id"):
                for task in all_tasks:
                    task["optimization_run_id"] = config["optimization_run_id"]
            self.config_store.write_json(config["output"], all_tasks)

        if config.get("ranking"):
            if not config.get("top_output"):
                raise ValueError("--ranking and --top-output must be provided together")
            top_tasks = render_top_symbol_tasks(
                template.as_dict(),
                self.config_store.load_json(config["ranking"]),
                top=int(config.get("top", 10)),
                rank_field=config.get("rank_field", DEFAULT_RANK_FIELD),
                min_return_pct=float(config.get("min_return_pct", 0)),
            )
            self.config_store.write_json(config["top_output"], top_tasks)

        return config


class RollingAnnualSelectionUseCase:
    """Walk monthly windows over a candidate universe and evaluate rolling top-N holds."""

    def __init__(
        self,
        *,
        config_store: TaskConfigFileStore,
        report_store: RankingReportStore,
        backtest_runner: BacktestRunner,
        warmup_candles: int = 500,
    ):
        self.config_store = config_store
        self.report_store = report_store
        self.backtest_runner = backtest_runner
        self.warmup_candles = warmup_candles

    @staticmethod
    def monthly_windows(year: int) -> list[MonthWindow]:
        return monthly_windows(year)

    async def execute(
        self,
        *,
        year: int,
        config_path: str,
        report_id: str,
        output_dir: str | None = None,
    ) -> dict[str, Any]:
        raw = self.config_store.load_json(config_path)
        config = parse_auto_selection_task(raw)
        template = config["template"]["task"]
        windows = monthly_windows(year)
        universe_payload = self.config_store.load_json(str(config["universe"]))
        universe = sorted(
            {
                item.get("symbol")
                for item in universe_payload.get("pairs", [])
                if item.get("symbol") and item.get("quote_asset") == "USDT"
            }
        )

        month_items: list[dict[str, Any]] = []
        monthly_returns: list[float] = []

        for window in windows:
            selection_results: list[SymbolRunResult] = []
            selection_reports: list[dict[str, Any]] = []
            selection_failures: list[dict[str, Any]] = []

            for symbol in universe:
                cfg_obj, selection_run = await self.backtest_runner.run_symbol_backtest(
                    template=template,
                    symbol=symbol,
                    start_time=window.selection_start,
                    end_time=window.selection_end,
                    optimization_run_id=f"{report_id}-{window.month}-select",
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

            ranking_payload = build_selection_payload(selection_results)
            top_candidates = select_top_symbols(ranking_payload, top=10, rank_field=DEFAULT_RANK_FIELD)
            selected_symbols = [item["symbol"] for item in top_candidates]

            hold_results: list[SymbolRunResult] = []
            for symbol in selected_symbols:
                cfg_obj, hold_run = await self.backtest_runner.run_symbol_backtest(
                    template=template,
                    symbol=symbol,
                    start_time=window.hold_start,
                    end_time=window.hold_end,
                    optimization_run_id=f"{report_id}-{window.month}-hold",
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

            monthly_return_pct = summary_return_pct(hold_results)
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
                    "cumulative_return_pct": compounded_return_pct(monthly_returns),
                    "selected_runs": [asdict(item) for item in hold_results],
                    "selection_failures": selection_failures,
                }
            )

            self.report_store.write_artifacts(
                f"{report_id}-{window.month}-selection",
                selection_reports,
                selection_failures,
            )

        result = {
            "report_id": report_id,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "year": year,
            "monthly": month_items,
            "final_return_pct": compounded_return_pct(monthly_returns),
            "monthly_returns_pct": monthly_returns,
            "methodology": {
                "selection_metric": "avg_total_return_pct",
                "selection_top_n": 10,
                "selection_window": "previous 12 calendar months",
                "holding_window": "current calendar month",
                "return_aggregation": "equal_weight_mean_return_pct",
                "compound_method": "monthly_compound_growth",
                "universe_source": config_path,
                "warmup_candles": self.warmup_candles,
            },
            "universe_size": len(universe),
        }
        self.report_store.write_rolling_outputs(report_id, result, month_items, output_dir=output_dir)
        return result
