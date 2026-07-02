from pathlib import Path

from trader.task.task_config import parse_task_config

ROOT = Path(__file__).resolve().parents[1]


def test_realtime_macd_production_tasks_cover_top_markets_with_hourly_live_config():
    tasks = parse_task_config(str(ROOT / "configs/tasks/live/auto_trade_macd_triple_divergence_top10_production.json"))

    symbols = [task.symbol_interval.symbol() for task in tasks]
    intervals = [task.symbol_interval.interval.value for task in tasks]
    assert list(zip(symbols, intervals)) == [
        ("BTCUSDT", "1h"),
        ("ETHUSDT", "1h"),
        ("BNBUSDT", "1h"),
        ("SOLUSDT", "1h"),
        ("XRPUSDT", "1h"),
        ("DOGEUSDT", "1h"),
        ("ADAUSDT", "1h"),
        ("TRXUSDT", "1h"),
        ("AVAXUSDT", "1h"),
        ("LINKUSDT", "1h"),
    ]
    assert len(set(symbols)) == 10
    for task in tasks:
        assert task.strategy_name() == "macd_triple_divergence"
        assert task.live_execution_mode == "auto_trade"
        assert not hasattr(task, "live_data_mode")
        assert task.strategy_params["chainer_stoploss_atr_mult"] == 1
        assert task.strategy_params["chainer_enable_breakeven"] is True
        assert task.strategy_params["chainer_risk_reward_ratio"] == 0
        assert task.strategy_params["chainer_need_confirm"] is False
        assert task.strategy_params["macd_stop_enabled"] is True
