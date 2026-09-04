import json
from pathlib import Path

import pytest

from trader.task.task_config import parse_task_config


def test_parse_task_config_reads_migrated_backtest_config_from_configs_directory():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "tasks" / "backtests" / "multi_backtrader.json"

    tasks = parse_task_config(str(config_path))

    assert len(tasks) > 9
    assert {task.strategy_name() for task in tasks} == {
        "ShihunMACD",
        "ShihunMACD2",
        "ShihunRSI",
        "ShihunRSI2",
        "ShihunMACDRISBB",
        "MACDRSI",
        "GRID",
        "BOLLMEANREG",
        "TURTLE",
    }


def test_parse_task_config_accepts_inline_json_after_config_migration():
    config = json.dumps(
        [
            {
                "task_type": "BACK_TRADER",
                "symbol": "BTC-USDT",
                "interval": "1h",
                "strategy": "macd_triple_divergence",
            }
        ]
    )

    tasks = parse_task_config(config)

    assert len(tasks) == 1
    assert tasks[0].strategy_name() == "macd_triple_divergence"
    assert tasks[0].start_time == int(parse_task_config.__globals__["parse_datetime"]("2000-01-01 00:00:00").timestamp())
    assert tasks[0].end_time >= tasks[0].start_time


def test_parse_task_config_reports_missing_config_file_path():
    with pytest.raises(ValueError, match="task config file does not exist"):
        parse_task_config("configs/tasks/live/realtime_macd_triple_divergence_top10_production.json")


def test_parse_task_config_expands_migrated_optimization_config_with_param_grid_fragments():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "tasks" / "optimizations" / "macd_triple_divergence_engine_optimization.json"

    tasks = parse_task_config(str(config_path))

    assert len(tasks) == 4320
    assert {
        task.strategy_params["chainer_need_confirm"]
        for task in tasks
    } == {False, True}


def test_parse_task_config_supports_relative_start_time():
    config = json.dumps(
        [
            {
                "task_type": "BACK_TRADER",
                "symbol": "BTC-USDT",
                "interval": "4h",
                "strategy": "macd_triple_divergence",
                "start_time": "1y",
            }
        ]
    )

    tasks = parse_task_config(config)

    assert len(tasks) == 1
    diff_days = (tasks[0].end_time - tasks[0].start_time) / 86400
    assert 364 <= diff_days <= 367


def test_parse_task_config_supports_relative_start_and_end_time():
    config = json.dumps(
        [
            {
                "task_type": "BACK_TRADER",
                "symbol": "BTC-USDT",
                "interval": "1h",
                "strategy": "macd_triple_divergence",
                "start_time": "30d",
                "end_time": "1d",
            }
        ]
    )

    tasks = parse_task_config(config)

    assert len(tasks) == 1
    diff_days = (tasks[0].end_time - tasks[0].start_time) / 86400
    assert 29.9 <= diff_days <= 30.1


def test_parse_task_config_loads_btc_4h_relative_config():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "tasks" / "backtests" / "btc_4h_macd_triple_divergence_single.json"

    tasks = parse_task_config(str(config_path))

    assert len(tasks) == 1
    assert tasks[0].strategy_name() == "macd_triple_divergence"
    assert tasks[0].symbol_interval.interval.value == "4h"
    diff_days = (tasks[0].end_time - tasks[0].start_time) / 86400
    assert 364 <= diff_days <= 367

