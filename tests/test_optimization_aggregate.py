from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from trader.core.optimization.domain import (
    CandidateSymbolSet,
    SelectionResultTaskConfig,
    TaskTemplate,
    build_cmc_binance_universe,
    build_optimization_artifacts,
    evaluate_abort_reason,
    expand_parameter_space,
    has_parameter_search,
    make_param_id,
    normalize_task_symbol,
    render_top_symbol_tasks,
    select_top_symbols,
    select_whitelist_usdt_symbols,
)
from trader.core.optimization.exceptions import OptimizationConfigError, RankingError
from trader.core.optimization.interfaces import (
    BacktestRunner,
    CandidateSymbolSource,
    RankingReportStore,
    TaskConfigFileStore,
)
from trader.core.optimization.use_cases import (
    AutoCoinSelectionUseCase,
    RollingAnnualSelectionUseCase,
    RunOptimizationAuditUseCase,
    RunParameterOptimizationUseCase,
)
from trader.core.shared.domain import Interval, SymbolInterval
from trader.core.task.config import TaskConfig
from trader.core.task.domain import TaskType


def test_optimization_exceptions_inherit_value_error():
    assert issubclass(OptimizationConfigError, ValueError)
    assert issubclass(RankingError, ValueError)


def test_task_template_rejects_overlapping_param_grid_fragments():
    template = TaskTemplate(
        task={
            "task_type": "BACK_TRADER",
            "symbols": "BTC-USDT",
            "interval": "1h",
            "strategy": [{"name": "macd_triple_divergence"}],
            "param_grid": {
                "a": [{"risk_reward_ratio": 2.0}],
                "b": [{"risk_reward_ratio": 3.0}],
            },
        }
    )
    with pytest.raises(OptimizationConfigError, match="overlaps existing keys"):
        template.expand_parameter_space()


def test_candidate_symbol_set_normalizes_and_renders_optimization_tasks():
    cmc_payload = {
        "data": {
            "constituents": [
                {"id": 1, "name": "Bitcoin", "symbol": "BTC", "weight": 60.0},
                {"id": 2, "name": "Ethereum", "symbol": "ETH", "weight": 30.0},
            ]
        }
    }
    binance_payload = {
        "symbols": [
            {"symbol": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT", "status": "TRADING", "isSpotTradingAllowed": True},
            {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "status": "TRADING", "isSpotTradingAllowed": True},
        ]
    }
    universe_payload = build_cmc_binance_universe(
        cmc_payload["data"],
        {"pairs": [
            {
                "symbol": item["symbol"],
                "base_asset": item["baseAsset"],
                "quote_asset": item["quoteAsset"],
                "status": item["status"],
                "margin_trading_allowed": False,
            }
            for item in binance_payload["symbols"]
        ]},
        index="CMC20",
        constituents_path="constituents.json",
    )
    candidate_set = CandidateSymbolSet.from_universe_payload(universe_payload)
    assert candidate_set.symbols == ["BTC-USDT", "ETH-USDT"]
    assert normalize_task_symbol("solusdt") == "SOL-USDT"
    assert select_whitelist_usdt_symbols(binance_payload, whitelist_bases=("BTC", "ETH")) == ["BTCUSDT", "ETHUSDT"]

    template = TaskTemplate(task={"task_type": "LIVE_TRADER", "strategy": [{"name": "macd_triple_divergence"}]})
    rendered = template.render_optimization_tasks(
        candidate_set,
        {"1h": "7d"},
        now=datetime(2026, 7, 15, 12, 30, 0),
    )
    assert len(rendered) == 1
    assert rendered[0]["task_type"] == "BACK_TRADER"
    assert rendered[0]["symbols"] == "BTC-USDT,ETH-USDT"
    assert rendered[0]["interval"] == "1h"
    assert rendered[0]["start_time"] == "2026-07-08 12:30:00"
    assert rendered[0]["end_time"] == "2026-07-15 12:30:00"


def test_selection_result_task_config_selects_and_validates_ranking():
    with pytest.raises(RankingError):
        select_top_symbols({"invalid": True})

    ranking = {
        "items": [
            {"symbol": "ETHUSDT", "interval": "1h", "avg_total_return_pct": 18.0, "score": 60.0, "param_id": "p1", "params": {"k": 1}},
            {"symbol": "BTCUSDT", "interval": "1h", "avg_total_return_pct": 25.0, "score": 70.0, "param_id": "p2", "params": {"k": 2}},
            {"symbol": "BTCUSDT", "interval": "1h", "avg_total_return_pct": 12.0, "score": 50.0, "param_id": "p3", "params": {"k": 3}},
        ]
    }
    template = TaskTemplate(
        task={
            "task_type": "LIVE_TRADER",
            "symbols": "OLD",
            "param_grid": {"k": [1, 2]},
            "start_time": "2026-01-01 00:00:00",
            "end_time": "2026-02-01 00:00:00",
            "strategy": [{"name": "macd_triple_divergence"}],
        }
    )
    rendered = render_top_symbol_tasks(template.as_dict(), ranking, top=2)
    assert [item["symbol"] for item in rendered] == ["BTC-USDT", "ETH-USDT"]
    assert rendered[0]["selection_param_id"] == "p2"
    assert "param_grid" not in rendered[0]
    assert "symbols" not in rendered[0]

    typed = SelectionResultTaskConfig.from_ranking_item(template, ranking["items"][1], rank=1)
    assert typed.to_task_dict()["symbol"] == "BTC-USDT"


def test_pure_domain_helpers_for_param_search_audit_and_abort():
    assert has_parameter_search({"param_grid": {"a": [1, 2]}})
    assert len(expand_parameter_space({"param_grid": {"a": [1, 2]}})) == 2
    assert len(make_param_id({"a": 1})) == 12
    assert (
        evaluate_abort_reason(
            {
                "stage": "running_samples",
                "completed_samples": 10,
                "failed_samples": 10,
                "timed_out_samples": 0,
            },
            max_failure_rate=0.9,
            min_completed_samples=5,
        )
        == "failure_rate_exceeded"
    )
    artifacts = build_optimization_artifacts(
        "run-1",
        [
            {
                "strategy": "macd_triple_divergence",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "optimization_run_id": "run-1",
                "param_id": "p1",
                "params": {"chainer_risk_reward_ratio": 2.0},
                "dataset_ref": "BTCUSDT-1h",
                "summary": {
                    "total_return_pct": 12.0,
                    "hold_return_pct": 5.0,
                    "sharpe": 1.2,
                    "profit_factor": 1.5,
                    "max_dd_pct": 4.0,
                    "total_trades": 1,
                    "total_signals": 1,
                },
                "trades": [{"exit_reason_code": "risk_reward_take_profit", "pnl_pct": 12.0, "bars_held": 2}],
                "signals": [{"bar_index": 1}],
            }
        ],
        [],
    )
    assert artifacts["rankings"]["by_score"][0]["symbol"] == "BTCUSDT"


class _FakeReportStore:
    def __init__(self) -> None:
        self.written_artifacts: list[tuple[str, list[dict], list[dict]]] = []
        self.summaries: list[tuple[str, dict]] = []
        self.rolling_outputs: list[tuple[str, dict, list[dict]]] = []
        self.sample_reports: dict[str, list[dict]] = {}
        self.failures: dict[str, list[dict]] = {}

    def load_sample_reports(self, run_id: str) -> list[dict]:
        return list(self.sample_reports.get(run_id, []))

    def load_failures(self, run_id: str) -> list[dict]:
        return list(self.failures.get(run_id, []))

    def write_artifacts(self, run_id: str, sample_reports: list[dict], failures: list[dict]) -> dict:
        self.written_artifacts.append((run_id, sample_reports, failures))
        return build_optimization_artifacts(run_id, sample_reports, failures)

    def write_agent_review_summary(self, run_id: str, summary: dict) -> str:
        self.summaries.append((run_id, summary))
        return f"reports/optimizations/{run_id}/agent_review_summary.json"

    def write_rolling_outputs(self, report_id: str, summary: dict, monthly_items: list[dict], output_dir: str | None = None) -> None:
        self.rolling_outputs.append((report_id, summary, monthly_items))


class _FakeConfigFileStore:
    def __init__(self, files: dict[str, dict]) -> None:
        self.files = dict(files)

    def exists(self, path: str) -> bool:
        return path in self.files

    def load_json(self, path: str) -> dict:
        return self.files[path]

    def write_json(self, path: str, payload: object) -> None:
        self.files[path] = payload


class _FakeSymbolSource:
    def fetch_binance_exchange_info(self) -> dict:
        return {
            "symbols": [
                {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "status": "TRADING", "isSpotTradingAllowed": True}
            ]
        }

    def fetch_cmc_index(self, index: str) -> dict:
        return {"data": {"constituents": [{"id": 1, "name": "Bitcoin", "symbol": "BTC", "weight": 100.0}]}}


class _FakeBacktestRunner:
    def __init__(self) -> None:
        self.prepared: list[int] = []
        self.executed: list[int] = []

    async def prepare_datasets(self, configs, runtimes=None):
        self.prepared.extend(cfg.id for cfg in configs)
        return []

    async def execute_samples(self, sample_specs):
        self.executed.extend(spec.task_id for spec in sample_specs)
        return [
            SimpleNamespace(
                ok=True,
                task_id=spec.task_id,
                trader_result={"return_pct": 10.0},
                logs=[],
                report={
                    "strategy": "macd_triple_divergence",
                    "symbol": "BTCUSDT",
                    "interval": "1h",
                    "optimization_run_id": spec.optimization_run_id,
                    "param_id": spec.param_id,
                    "params": {},
                    "dataset_ref": "BTCUSDT-1h",
                    "summary": {
                        "total_return_pct": 10.0,
                        "hold_return_pct": 2.0,
                        "sharpe": 1.0,
                        "profit_factor": 1.5,
                        "max_dd_pct": 3.0,
                        "total_trades": 1,
                        "total_signals": 1,
                    },
                    "trades": [{"exit_reason_code": "risk_reward_take_profit", "pnl_pct": 10.0, "bars_held": 1}],
                    "signals": [{"bar_index": 1}],
                },
                report_path="run.json",
                error=None,
                timed_out=False,
            )
            for spec in sample_specs
        ]


def test_core_optimization_ports_and_use_cases_work_without_io():
    assert isinstance(_FakeReportStore(), RankingReportStore)
    assert isinstance(_FakeConfigFileStore({}), TaskConfigFileStore)
    assert isinstance(_FakeSymbolSource(), CandidateSymbolSource)
    assert isinstance(_FakeBacktestRunner(), BacktestRunner)

    report_store = _FakeReportStore()
    report_store.sample_reports["opt-1"] = [
        {
            "strategy": "macd_triple_divergence",
            "symbol": "BTCUSDT",
            "interval": "1h",
            "optimization_run_id": "opt-1",
            "param_id": "p1",
            "params": {"chainer_risk_reward_ratio": 1.0},
            "dataset_ref": "BTCUSDT-1h",
            "summary": {
                "total_return_pct": 10.0,
                "hold_return_pct": 2.0,
                "sharpe": 1.0,
                "profit_factor": 1.5,
                "max_dd_pct": 3.0,
                "total_trades": 1,
                "total_signals": 1,
            },
            "trades": [{"exit_reason_code": "risk_reward_take_profit", "pnl_pct": 10.0, "bars_held": 1}],
            "signals": [{"bar_index": 1}],
        }
    ]
    audit_result = RunOptimizationAuditUseCase(report_store).execute("opt-1", block_on_failure=False)
    assert audit_result["status"] == "passed"
    assert len(report_store.summaries) == 1

    config_store = _FakeConfigFileStore(
        {
            "auto.json": {
                "task_type": "AUTO_SELECTION",
                "market_data": {"index": "CMC20", "binance_pairs": "pairs.json", "constituents": "cmc.json"},
                "universe": "universe.json",
                "task_template": {"task_type": "LIVE_TRADER", "strategy": [{"name": "macd_triple_divergence"}]},
                "optimization": {"output": "opt_tasks.json", "run_id": "opt-1", "profiles": {"1h": "7d"}},
                "selection": {"live_output": "top.json", "top": 5, "rank_field": "avg_total_return_pct", "min_return_pct": 0},
            }
        }
    )
    AutoCoinSelectionUseCase(config_store=config_store, symbol_source=_FakeSymbolSource()).execute(
        config_path="auto.json",
        now=datetime(2026, 7, 15, 12, 30, 0),
    )
    assert len(config_store.files["opt_tasks.json"]) == 1
    assert config_store.files["opt_tasks.json"][0]["symbols"] == "BTC-USDT"
    assert config_store.files["opt_tasks.json"][0]["optimization_run_id"] == "opt-1"


def test_run_parameter_optimization_use_case_with_fake_runner():
    runner = _FakeBacktestRunner()
    report_store = _FakeReportStore()
    cfg_obj = TaskConfig(
        id=1,
        ttype=TaskType.BACK_TRADER,
        symbol_interval=SymbolInterval("BTC-USDT", Interval.INTERVAL_1h),
        optimization_run_id="opt-2",
        strategies=["macd_triple_divergence"],
    )

    events: list[tuple[str, int]] = []

    async def on_sample_result(cfg, sample_result):
        events.append(("sample", cfg.id))

    use_case = RunParameterOptimizationUseCase(
        backtest_runner=runner,
        report_store=report_store,
        max_workers=2,
    )
    asyncio.run(
        use_case.execute(
            [cfg_obj],
            sample_spec_builder=lambda cfg: SimpleNamespace(task_id=cfg.id, optimization_run_id=cfg.optimization_run_id, param_id=cfg.param_id),
            on_sample_result=on_sample_result,
        )
    )
    assert runner.prepared == [1]
    assert runner.executed == [1]
    assert events == [("sample", 1)]
    assert len(report_store.written_artifacts) == 1
    assert report_store.written_artifacts[0][0] == "opt-2"


def test_rolling_annual_selection_use_case_exists_and_exposes_monthly_windows():
    windows = RollingAnnualSelectionUseCase.monthly_windows(2025)
    assert len(windows) == 12
    assert windows[0].month == "2025-01"
