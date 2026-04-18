import json
from pathlib import Path

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


def test_parse_task_config_expands_migrated_optimization_config_with_param_grid_fragments():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "tasks" / "optimizations" / "macd_triple_divergence_engine_optimization.json"

    tasks = parse_task_config(str(config_path))

    assert len(tasks) == 4320
    assert {
        task.strategy_params["chainer_need_confirm"]
        for task in tasks
    } == {False, True}
