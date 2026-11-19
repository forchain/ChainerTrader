from datetime import datetime
from types import SimpleNamespace

from trader.core.task.domain import (
    Task,
    TaskState,
    TaskStateType,
    bounded_results,
    can_transition,
    collect_operates,
    parse_task_state,
    rank_results,
    result_return_rate,
)


def _stat(strategy: str, total_return_rate: float, operate=None):
    tret = SimpleNamespace(total_return_rate=total_return_rate)
    if operate is not None:
        tret.operate = operate
    return SimpleNamespace(strategy=strategy, ts=SimpleNamespace(tret=tret))


def test_task_state_round_trip_preserves_config_json():
    config_json = '[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1h","strategy":"s"}]'
    state = TaskState(1, "task", datetime(2026, 1, 1), config_json=config_json, user_id=7)

    restored = parse_task_state(state.to_dict())

    assert restored.config_json == config_json
    assert restored.user_id == 7


def test_task_is_the_task_state_aggregate_snapshot():
    assert Task is TaskState


def test_lifecycle_rules_allow_forward_transitions_only():
    assert can_transition(TaskStateType.READY, TaskStateType.RUNNING)
    assert can_transition(TaskStateType.RUNNING, TaskStateType.DONE)
    assert can_transition(TaskStateType.RUNNING, TaskStateType.FAILED)
    assert not can_transition(TaskStateType.DONE, TaskStateType.RUNNING)
    assert not can_transition(TaskStateType.FAILED, TaskStateType.DONE)


def test_task_state_lifecycle_helpers_track_state_and_error():
    state = TaskState(1, "task", datetime(2026, 1, 1))

    assert not state.is_running()
    state.mark_running()
    assert state.is_running()
    assert not state.is_terminal()
    state.mark_failed("startup failed")
    assert state.state == TaskStateType.FAILED
    assert state.is_terminal()
    assert state.error_message == "startup failed"


def test_result_ranking_sorts_descending_and_bounds_to_limit():
    stats = [_stat("low", 1.0), _stat("high", 3.0), _stat("mid", 2.0)]

    assert [stat.strategy for stat in rank_results(stats)] == ["high", "mid", "low"]
    assert [stat.strategy for stat in bounded_results(stats, 2)] == ["high", "mid"]
    assert bounded_results(stats, 0) is stats
    assert result_return_rate(stats[0]) == 1.0


def test_bounded_results_ignores_stats_without_results():
    without_result = SimpleNamespace(strategy="missing", ts=SimpleNamespace(tret=None))

    assert result_return_rate(without_result) is None
    assert bounded_results([without_result], 1) == [without_result]


def test_collect_operates_returns_operation_payloads_up_to_limit():
    first = SimpleNamespace(to_dict=lambda: {"type": "BUY"})
    second = SimpleNamespace(to_dict=lambda: {"type": "SELL"})
    stats = [_stat("a", 1.0, first), _stat("b", 2.0), _stat("c", 3.0, second)]

    assert collect_operates(stats, 2) == [{"type": "BUY"}, {"type": "SELL"}]


def test_task_config_is_exposed_by_the_core_task_package():
    from trader.adapters.outbound.files.task_config_loader import TaskConfig as LegacyTaskConfig
    from trader.core.task import TaskConfig
    from trader.core.task.domain import TaskConfig as DomainTaskConfig

    assert TaskConfig is LegacyTaskConfig
    assert DomainTaskConfig is LegacyTaskConfig
