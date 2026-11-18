import json
from datetime import datetime

import pytest

from trader.task.task_config import TaskConfig
from trader.task.task_config_codec import TaskConfigCodec
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import Interval, SymbolInterval
from trader.utils.task_state import TaskState


def _trader_config(task_id: int = 123) -> TaskConfig:
    return TaskConfig(
        task_id,
        TaskType.TRADER,
        SymbolInterval("BTC-USDT", Interval("1m")),
        strategies=["macd_triple_divergence"],
        free=10000,
        strategy_params={"chainer_mode": "LONG_ONLY"},
        live_execution_mode="manual_notify",
        live_trade_max_notional=12.0,
        live_margin_borrow_block_policy="repay_all",
        live_margin_borrow_precheck=False,
        user_id=7,
        run_id="run-42",
    )


def test_codec_round_trip_preserves_task_user_and_run_ids():
    cfg = _trader_config()

    state = TaskConfigCodec.to_task_state(cfg, name="t", commission=0.1, initial_cash=10000)
    restored = TaskConfigCodec.from_persisted_state(state)

    assert restored is not None
    assert restored.id == cfg.id
    assert restored.user_id == cfg.user_id
    assert restored.run_id == cfg.run_id
    assert restored.live_execution_mode == "manual_notify"
    assert restored.live_trade_max_notional == 12.0
    assert restored.strategy_params == {"chainer_mode": "LONG_ONLY"}


def test_codec_persisted_state_uses_state_id_over_minted_id():
    cfg = _trader_config()
    state = TaskConfigCodec.to_task_state(cfg)
    state.id = 999

    restored = TaskConfigCodec.from_persisted_state(state)

    assert restored is not None
    assert restored.id == 999


def test_codec_from_input_expands_candidate_symbols_and_relative_time():
    raw = json.dumps(
        [
            {
                "task_type": "UPDATE_KLINES",
                "symbols": "BTC-USDT,ETH-USDT",
                "interval": "1h",
                "start_time": "-2d",
            }
        ]
    )

    taskcs = TaskConfigCodec.from_input(raw)

    assert [tc.symbol_interval.symbol() for tc in taskcs] == ["BTCUSDT", "ETHUSDT"]
    assert all(tc.start_time > 0 for tc in taskcs)


def test_codec_from_input_normalizes_strategy_confirmation_params():
    raw = json.dumps(
        [
            {
                "task_type": "BACK_TRADER",
                "symbol": "BTC-USDT",
                "interval": "1m",
                "strategy": "ShihunRSI",
                "strategy_params": {"chainer_enter_need_confirm": True, "chainer_exit_need_confirm": True},
            }
        ]
    )

    taskc = TaskConfigCodec.from_input(raw)[0]

    assert taskc.strategy_params == {"chainer_need_confirm": True}


def test_codec_persisted_state_applies_legacy_runtime_metadata():
    state = TaskState(
        5,
        "t",
        datetime(2024, 1, 1),
        config_json=(
            '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m",'
            '"strategy":"macd_triple_divergence","live_execution_mode":"auto_trade",'
            '"persisted_legacy_live_execution_mode":"small_live_auto","user_id":3,"run_id":"run-5"}]'
        ),
        user_id=3,
    )

    restored = TaskConfigCodec.from_persisted_state(state)

    assert restored is not None
    assert restored.id == 5
    assert restored.user_id == 3
    assert restored.run_id == "run-5"
    assert restored.persisted_legacy_live_execution_mode == "small_live_auto"


def test_codec_persisted_state_rejects_unmigrated_legacy_mode():
    state = TaskState(
        6,
        "t",
        datetime(2024, 1, 1),
        config_json=(
            '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m",'
            '"strategy":"macd_triple_divergence","live_execution_mode":"small_live_auto"}]'
        ),
        user_id=3,
    )

    with pytest.raises(RuntimeError, match=r"persisted live task\(6\) recovery failed"):
        TaskConfigCodec.from_persisted_state(state)


def test_codec_to_public_view_redacts_persisted_runtime_markers_and_derives_fields():
    state = TaskState(
        8,
        "t",
        datetime(2024, 1, 1),
        config_json=(
            '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1m","strategy":"ShihunRSI",'
            '"run_id":"run-8","persisted_legacy_live_execution_mode":"small_live_auto",'
            '"persisted_live_data_mode":"realtime"}]'
        ),
        user_id=3,
    )

    view = TaskConfigCodec.to_public_view(state)

    payload = json.loads(view["config_json"])[0]
    assert "persisted_legacy_live_execution_mode" not in payload
    assert "persisted_live_data_mode" not in payload
    assert view["run_id"] == "run-8"
    assert view["symbol"] == "BTC-USDT"
    assert view["interval"] == "1m"
    assert view["strategy"] == "ShihunRSI"


def test_codec_round_trip_preserves_update_klines_fields():
    cfg = TaskConfig(
        321,
        TaskType.UPDATE_KLINES,
        SymbolInterval("BTC-USDT", Interval("1h")),
        limit=250,
        force_update=True,
    )

    restored = TaskConfigCodec.from_persisted_state(TaskConfigCodec.to_task_state(cfg))

    assert restored is not None
    assert restored.limit == 250
    assert restored.force_update is True


def test_codec_round_trip_preserves_param_and_optimization_ids():
    cfg = TaskConfig(
        322,
        TaskType.BACK_TRADER,
        SymbolInterval("BTC-USDT", Interval("1h")),
        strategies=["ShihunRSI"],
        strategy_params={"rsi_period": 14},
        param_id="param-abc",
        optimization_run_id="opt-run-9",
    )

    restored = TaskConfigCodec.from_persisted_state(TaskConfigCodec.to_task_state(cfg))

    assert restored is not None
    assert restored.param_id == "param-abc"
    assert restored.optimization_run_id == "opt-run-9"


def test_codec_round_trip_preserves_missing_run_id_without_minting():
    cfg = _trader_config()
    cfg.run_id = None

    restored = TaskConfigCodec.from_persisted_state(TaskConfigCodec.to_task_state(cfg))

    assert restored is not None
    assert restored.run_id is None
