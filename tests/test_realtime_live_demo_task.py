from pathlib import Path

from trader.task.task_config import parse_task_config

ROOT = Path(__file__).resolve().parents[1]


def test_realtime_macd_production_tasks_cover_top_markets_with_daily_and_btc_intraday():
    tasks = parse_task_config(str(ROOT / "configs/tasks/live/realtime_macd_triple_divergence_top10_production.json"))

    symbols = [task.symbol_interval.symbol() for task in tasks]
    intervals = [task.symbol_interval.interval.value for task in tasks]
    assert list(zip(symbols, intervals)) == [
        ("BTCUSDT", "1m"),
        ("BTCUSDT", "1d"),
        ("ETHUSDT", "1d"),
        ("BNBUSDT", "1d"),
        ("SOLUSDT", "1d"),
        ("XRPUSDT", "1d"),
        ("DOGEUSDT", "1d"),
        ("ADAUSDT", "1d"),
        ("TRXUSDT", "1d"),
        ("AVAXUSDT", "1d"),
        ("LINKUSDT", "1d"),
    ]
    assert len(set(symbols)) == 10
    for task in tasks:
        assert task.strategy_name() == "macd_triple_divergence"
        assert task.live_execution_mode == "manual_notify"
        assert task.live_data_mode == "realtime"
        assert task.strategy_params["chainer_stoploss_atr_mult"] == 1
        assert task.strategy_params["chainer_enable_breakeven"] is True
        assert task.strategy_params["chainer_risk_reward_ratio"] == 0
        assert task.strategy_params["chainer_need_confirm"] is True
        assert task.strategy_params["macd_stop_enabled"] is True
