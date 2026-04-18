import json

import pytest

from trader.task.task_config import parse_task_config


def test_parse_task_config_expands_param_grid_into_cartesian_product():
    config = json.dumps(
        [
            {
                "task_type": "BACK_TRADER",
                "symbol": "BTC-USDT",
                "interval": "1h",
                "strategy": "macd_triple_divergence",
                "param_grid": {
                    "fast_period": [5, 8],
                    "slow_period": [20, 30],
                },
            }
        ]
    )

    tasks = parse_task_config(config)

    assert len(tasks) == 4
    assert {tuple(sorted(task.strategy_params.items())) for task in tasks} == {
        (("fast_period", 5), ("slow_period", 20)),
        (("fast_period", 5), ("slow_period", 30)),
        (("fast_period", 8), ("slow_period", 20)),
        (("fast_period", 8), ("slow_period", 30)),
    }
    assert all(task.optimization_run_id for task in tasks)
    assert len({task.param_id for task in tasks}) == 4


def test_parse_task_config_expands_param_grid_with_linked_parameter_fragments():
    config = json.dumps(
        [
            {
                "task_type": "BACK_TRADER",
                "symbol": "BTC-USDT",
                "interval": "1h",
                "strategy": "macd_triple_divergence",
                "param_grid": {
                    "chainer_mode": ["LONG_ONLY", "SHORT_ONLY"],
                    "confirm_pair": [
                        {"chainer_need_confirm": False},
                        {"chainer_need_confirm": True},
                    ],
                },
            }
        ]
    )

    tasks = parse_task_config(config)

    assert len(tasks) == 4
    assert {tuple(sorted(task.strategy_params.items())) for task in tasks} == {
        (("chainer_mode", "LONG_ONLY"), ("chainer_need_confirm", False)),
        (("chainer_mode", "LONG_ONLY"), ("chainer_need_confirm", True)),
        (("chainer_mode", "SHORT_ONLY"), ("chainer_need_confirm", False)),
        (("chainer_mode", "SHORT_ONLY"), ("chainer_need_confirm", True)),
    }


def test_param_combinations_override_param_grid():
    config = json.dumps(
        [
            {
                "task_type": "BACK_TRADER",
                "symbol": "BTC-USDT",
                "interval": "1h",
                "strategy": "macd_triple_divergence",
                "param_grid": {
                    "fast_period": [5, 8],
                    "slow_period": [20, 30],
                },
                "param_combinations": [
                    {"fast_period": 5, "slow_period": 20},
                    {"fast_period": 8, "slow_period": 30},
                ],
            }
        ]
    )

    tasks = parse_task_config(config)

    assert len(tasks) == 2
    assert [task.strategy_params for task in tasks] == [
        {"fast_period": 5, "slow_period": 20},
        {"fast_period": 8, "slow_period": 30},
    ]


def test_parameter_search_requires_single_strategy_entry():
    config = json.dumps(
        [
            {
                "task_type": "BACK_TRADER",
                "symbol": "BTC-USDT",
                "interval": "1h",
                "strategies": "macd_triple_divergence,super_trend_qqe_mod",
                "param_grid": {
                    "fast_period": [5, 8],
                },
            }
        ]
    )

    with pytest.raises(ValueError, match="single strategy"):
        parse_task_config(config)


def test_parse_task_config_keeps_legacy_backtest_behavior_without_parameter_search():
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
    assert tasks[0].strategy_params == {}
    assert tasks[0].param_id is None
    assert tasks[0].optimization_run_id is None


def test_parameter_search_uses_launch_run_id_from_environment(monkeypatch):
    monkeypatch.setenv("TRADER_OPTIMIZATION_RUN_ID", "run-launch-123")
    config = json.dumps(
        [
            {
                "task_type": "BACK_TRADER",
                "symbol": "BTC-USDT",
                "interval": "1h",
                "strategy": "macd_triple_divergence",
                "param_grid": {
                    "fast_period": [5, 8],
                },
            }
        ]
    )

    tasks = parse_task_config(config)

    assert {task.optimization_run_id for task in tasks} == {"run-launch-123"}
