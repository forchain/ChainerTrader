from pathlib import Path

from trader.task.task_config import parse_task_config

ROOT = Path(__file__).resolve().parents[1]


def test_realtime_btc_1m_macd_demo_task_is_parseable_and_uses_manual_notify_risk_params():
    tasks = parse_task_config(str(ROOT / "configs/tasks/live/realtime_macd_triple_divergence_btc_1m_demo.json"))

    assert len(tasks) == 1
    task = tasks[0]
    assert task.symbol_interval.symbol() == "BTCUSDT"
    assert task.symbol_interval.interval.value == "1m"
    assert task.strategy_name() == "macd_triple_divergence"
    assert task.live_execution_mode == "manual_notify"
    assert task.live_data_mode == "realtime"
    assert task.strategy_params["chainer_stoploss_atr_mult"] == 1
    assert task.strategy_params["chainer_enable_breakeven"] is True
    assert task.strategy_params["chainer_risk_reward_ratio"] == 0
    assert task.strategy_params["chainer_need_confirm"] is True
    assert task.strategy_params["macd_stop_enabled"] is True
