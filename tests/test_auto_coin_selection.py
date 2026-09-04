import json
from datetime import datetime
from pathlib import Path

import pytest

from trader.tools.auto_coin_selection import (
    CMC_INDEXES,
    DEFAULT_CONFIG_PATH,
    build_cmc_binance_universe,
    ensure_market_data,
    load_auto_selection_task,
    load_universe_symbols,
    merge_auto_selection_config,
    render_all_symbol_tasks,
    render_optimization_tasks,
    render_top_symbol_tasks,
    resolve_task_time_range,
    select_top_symbols,
)


def test_build_cmc_binance_universe_keeps_cmc_order_and_binance_usdt_matches():
    cmc = {
        "constituents": [
            {"id": 1, "name": "Bitcoin", "symbol": "BTC", "weight": 60.0},
            {"id": 2, "name": "Missing", "symbol": "MISS", "weight": 20.0},
            {"id": 3, "name": "Ethereum", "symbol": "ETH", "weight": 10.0},
        ]
    }
    binance = {
        "pairs": [
            {"symbol": "ETHUSDT", "base_asset": "ETH", "quote_asset": "USDT", "status": "TRADING"},
            {"symbol": "BTCUSDT", "base_asset": "BTC", "quote_asset": "USDT", "status": "TRADING"},
        ]
    }

    universe = build_cmc_binance_universe(cmc, binance, index="CMC20", constituents_path="data/market_universes/cmc20_constituents.json")

    assert universe["count"] == 2
    assert universe["symbols"] == "BTC-USDT,ETH-USDT"
    assert universe["market_index"] == "CMC20"
    assert universe["source_files"][0] == "data/market_universes/cmc20_constituents.json"
    assert [item["cmc_name"] for item in universe["pairs"]] == ["Bitcoin", "Ethereum"]


def test_cmc20_and_cmc100_have_distinct_provider_definitions():
    assert CMC_INDEXES["CMC20"]["api_url"].endswith("/cmc20-latest")
    assert CMC_INDEXES["CMC20"]["source_url"] == "https://coinmarketcap.com/charts/cmc20/"
    assert CMC_INDEXES["CMC100"]["api_url"].endswith("/cmc100-latest")


def test_load_universe_symbols_reads_pair_payload(tmp_path):
    path = tmp_path / "universe.json"
    path.write_text(
        json.dumps({"pairs": [{"symbol": "BTC-USDT"}, {"exchange_symbol": "ETHUSDT"}, {"symbol": "币安人生-USDT"}]}),
        encoding="utf-8",
    )

    assert load_universe_symbols(path) == ["BTC-USDT", "ETH-USDT"]


def test_render_all_symbol_tasks_injects_symbols_without_mutating_template():
    template = {"task": {"task_type": "TRADER", "symbols": "${symbols}", "interval": "1d"}}

    tasks = render_all_symbol_tasks(template, ["BTC-USDT", "ETH-USDT"])

    assert tasks == [{"task_type": "BACK_TRADER", "symbols": "BTC-USDT,ETH-USDT", "interval": "1d"}]
    assert template["task"] == {"task_type": "TRADER", "symbols": "${symbols}", "interval": "1d"}


def test_render_optimization_tasks_generates_each_profile_with_its_own_time_range():
    template = {"task": {"task_type": "TRADER", "strategy": "macd_triple_divergence"}}

    tasks = render_optimization_tasks(
        template,
        ["BTC-USDT", "ETH-USDT"],
        {"1h": "1M", "4h": "1Y", "1d": "*"},
        now=datetime(2026, 7, 15, 12, 30, 0),
    )

    assert [(task["interval"], task["start_time"], task["end_time"]) for task in tasks] == [
        ("1h", "2026-06-15 12:30:00", "2026-07-15 12:30:00"),
        ("4h", "2025-07-15 12:30:00", "2026-07-15 12:30:00"),
        ("1d", "2000-01-01 00:00:00", "2026-07-15 12:30:00"),
    ]
    assert all(task["task_type"] == "BACK_TRADER" for task in tasks)
    assert all(task["symbols"] == "BTC-USDT,ETH-USDT" for task in tasks)
    assert template == {"task": {"task_type": "TRADER", "strategy": "macd_triple_divergence"}}


def test_select_top_symbols_keeps_best_result_per_symbol():
    ranking = [
        {"symbol": "BTCUSDT", "avg_total_return_pct": 3.0, "score": 50, "param_id": "slow"},
        {"symbol": "ETHUSDT", "avg_total_return_pct": 6.0, "score": 40, "param_id": "eth"},
        {"symbol": "BTCUSDT", "avg_total_return_pct": 8.0, "score": 55, "param_id": "fast"},
    ]

    selected = select_top_symbols(ranking, top=2)

    assert [(item["symbol"], item["param_id"]) for item in selected] == [("BTCUSDT", "fast"), ("ETHUSDT", "eth")]


def test_select_top_symbols_keeps_best_result_per_symbol_and_interval_and_applies_strict_return_threshold():
    ranking = [
        {"symbol": "BTCUSDT", "interval": "1h", "avg_total_return_pct": 8.0, "param_id": "btc-1h-best"},
        {"symbol": "BTCUSDT", "interval": "1h", "avg_total_return_pct": 2.0, "param_id": "btc-1h-worse"},
        {"symbol": "BTCUSDT", "interval": "1d", "avg_total_return_pct": 4.0, "param_id": "btc-1d"},
        {"symbol": "ETHUSDT", "interval": "4h", "avg_total_return_pct": 0.0, "param_id": "eth-flat"},
    ]

    selected = select_top_symbols(ranking, top=10, min_return_pct=0)

    assert [(item["symbol"], item["interval"], item["param_id"]) for item in selected] == [
        ("BTCUSDT", "1h", "btc-1h-best"),
        ("BTCUSDT", "1d", "btc-1d"),
    ]


def test_render_top_symbol_tasks_writes_rank_metadata_and_params():
    template = {
        "task": {
            "task_type": "BACK_TRADER",
            "symbols": "${symbols}",
            "interval": "1d",
            "strategy": "macd_triple_divergence",
            "param_combinations": [{"unused": [1]}],
        }
    }
    ranking = [
        {
            "symbol": "BTCUSDT",
            "interval": "4h",
            "avg_total_return_pct": 8.5,
            "score": 60,
            "param_id": "btc-param",
            "params": {"chainer_mode": "LONG_ONLY"},
        }
    ]

    tasks = render_top_symbol_tasks(template, ranking)

    assert tasks == [
        {
            "task_type": "BACK_TRADER",
            "interval": "4h",
            "strategy": "macd_triple_divergence",
            "symbol": "BTC-USDT",
            "strategy_params": {"chainer_mode": "LONG_ONLY"},
            "selection_rank": 1,
            "selection_metric": "avg_total_return_pct",
            "selection_metric_value": 8.5,
            "selection_param_id": "btc-param",
        }
    ]


def test_render_top_symbol_tasks_preserves_template_task_type_for_final_execution():
    template = {
        "task": {
            "task_type": "TRADER",
            "strategy": "macd_triple_divergence",
            "start_time": "2026-06-01 00:00:00",
            "end_time": "2026-07-01 00:00:00",
        }
    }
    ranking = [{"symbol": "BTCUSDT", "interval": "1h", "avg_total_return_pct": 8.5, "params": {}}]

    tasks = render_top_symbol_tasks(template, ranking)

    assert tasks[0]["task_type"] == "TRADER"
    assert tasks[0]["interval"] == "1h"
    assert "start_time" not in tasks[0]
    assert "end_time" not in tasks[0]


def test_auto_selection_configs_are_the_single_source_of_their_template_and_outputs():
    config_path = Path(__file__).parents[1] / DEFAULT_CONFIG_PATH
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert config["task_type"] == "AUTO_SELECTION"
    assert config["market_data"]["index"] == "CMC20"
    assert config["optimization"]["profiles"] == {"1h": "1M", "4h": "1Y", "1d": "*"}
    assert config["selection"]["min_return_pct"] == 0
    assert config["task_template"]["task_type"] == "TRADER"
    assert "interval" not in config["task_template"]
    assert "start_time" not in config["task_template"]

    runtime_config = load_auto_selection_task(config_path)

    assert runtime_config["template"]["task"] == config["task_template"]
    assert runtime_config["output"] == config["optimization"]["output"]
    assert runtime_config["top_output"] == config["selection"]["live_output"]
    assert runtime_config["profiles"] == config["optimization"]["profiles"]


def test_cmc100_config_remains_available_as_an_explicit_single_hour_profile():
    config_path = Path(__file__).parents[1] / "configs/tasks/auto_selection/cmc100_binance_usdt_auto_selection.json"

    runtime_config = load_auto_selection_task(config_path)

    assert runtime_config["index"] == "CMC100"
    assert runtime_config["profiles"] == {"1h": "1M"}


def test_merge_auto_selection_config_uses_cli_values_over_config_defaults():
    config = {
        "template": "configs/tasks/templates/default.json",
        "top": 10,
        "refresh_market_data": False,
    }

    merged = merge_auto_selection_config(config, {"template": None, "top": 20, "refresh_market_data": True})

    assert merged == {
        "template": "configs/tasks/templates/default.json",
        "top": 20,
        "refresh_market_data": True,
    }


def test_ensure_market_data_uses_existing_files_unless_refresh_is_enabled(tmp_path):
    binance_path = tmp_path / "binance.json"
    cmc_path = tmp_path / "cmc.json"
    binance_path.write_text(json.dumps({"pairs": [{"symbol": "BTCUSDT"}]}), encoding="utf-8")
    cmc_path.write_text(json.dumps({"constituents": [{"symbol": "BTC"}]}), encoding="utf-8")
    fetched: list[str] = []

    def fetch_json(url: str) -> dict:
        fetched.append(url)
        return {"data": {"constituents": []}} if "coinmarketcap" in url else {"symbols": []}

    ensure_market_data(
        binance_path=binance_path,
        constituents_path=cmc_path,
        index="CMC20",
        refresh=False,
        fetch_json=fetch_json,
    )
    assert fetched == []

    ensure_market_data(
        binance_path=binance_path,
        constituents_path=cmc_path,
        index="CMC20",
        refresh=True,
        fetch_json=fetch_json,
    )
    assert len(fetched) == 2


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        ("1H", "2026-07-15 11:30:00"),
        ("7D", "2026-07-08 12:30:00"),
        ("1W", "2026-07-08 12:30:00"),
        ("1M", "2026-06-15 12:30:00"),
    ],
)
def test_resolve_task_time_range_resolves_relative_end_time_from_now(duration, expected):
    task = {"end_time": duration}
    now = datetime(2026, 7, 15, 12, 30, 0)

    resolved = resolve_task_time_range(task, now=now)

    assert resolved["end_time"] == expected


def test_resolve_task_time_range_resolves_relative_start_time_from_now():
    task = {"start_time": "1M"}

    resolved = resolve_task_time_range(
        task,
        now=datetime(2026, 7, 15, 12, 30, 0),
    )

    assert resolved["start_time"] == "2026-06-15 12:30:00"
    assert resolved["end_time"] == "2026-07-15 12:30:00"


@pytest.mark.parametrize("field", ["start_time", "end_time"])
def test_resolve_task_time_range_rejects_textual_durations(field):
    with pytest.raises(ValueError, match=field):
        resolve_task_time_range({field: "one month"}, now=datetime(2026, 7, 15, 12, 30, 0))
