from datetime import datetime
from zoneinfo import ZoneInfo

from trader.tools.live_signal_reconciliation import (
    ExecutionAudit,
    ReplayOperation,
    RuntimeEvidence,
    compare_operations,
    parse_runtime_evidence,
    summarize_execution_audit,
    validate_market_data,
)
from trader.utils.kline import Kline

TZ = ZoneInfo("Asia/Shanghai")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


def test_parse_runtime_evidence_excludes_warmup_and_correlates_submission():
    warmup_ignored = (
        "2026-07-03 10:13:37,100[INFO:trader] Realtime warmup operation ignored for auto execution: "
        "task_id=7 strategy=macd_triple_divergence operation=SHORT event_time=100"
    )
    warmup_signal = (
        "2026-07-03 10:13:37,101[INFO:trader] Realtime strategy signal: task_id=7 "
        "strategy=macd_triple_divergence stream=dogeusdt@kline_1h open_time=100 operations=1 "
        "op_types=[SHORT] notifications=0 execution_outcomes=0"
    )
    submitted = (
        "2026-07-04 01:00:50,772[INFO:trader] [auto_execution] submitted "
        "{'task_id': 7, 'mode': 'auto_trade', 'market': 'DOGEUSDT', "
        "'operation_id': 'signal_event_id:3', 'operation_type': 'SHORT', 'status': 'submitted', "
        "'reason': None, 'order_id': 'entry-1', 'effective_quantity': 1.0, "
        "'effective_notional': 11.0, 'margin_borrow_control': {}}"
    )
    live_signal = (
        "2026-07-04 01:00:50,877[INFO:trader] Realtime strategy signal: task_id=7 "
        "strategy=macd_triple_divergence stream=dogeusdt@kline_1h open_time=200 operations=1 "
        "op_types=[SHORT] notifications=0 execution_outcomes=1"
    )
    text = "\n".join(
        [
            "2026-07-03 10:13:36,717[INFO:trader] Realtime live warmup started: task_id=7 collection=DOGEUSDT-1h target=500",
            warmup_ignored,
            warmup_signal,
            submitted,
            live_signal,
            "2026-07-12 00:01:45,428[INFO:root] CCXT polling scheduler stream removed: stream=dogeusdt@kline_1h reason=websocket disconnected",
            "2026-07-13 21:01:39,826[INFO:root] CCXT polling scheduler stream registered: stream=dogeusdt@kline_1h min_request_spacing_seconds=10.0",
            "2026-07-13 22:45:08,231[INFO:trader] Realtime live warmup started: task_id=7 collection=DOGEUSDT-1h target=100",
        ]
    )

    evidence = parse_runtime_evidence(text, _dt("2026-07-01T00:00:00"), _dt("2026-07-14T16:01:25"))

    assert [(session.target, session.task_id) for session in evidence.sessions["DOGEUSDT"]] == [(500, 7), (100, 7)]
    assert len(evidence.operations) == 1
    assert evidence.operations[0].signal_event_id == "3"
    assert evidence.operations[0].session_started_at == _dt("2026-07-03T10:13:36")
    assert len(evidence.audits) == 1
    assert evidence.outages["DOGEUSDT"][0].started_at == _dt("2026-07-12T00:01:45")
    assert evidence.outages["DOGEUSDT"][0].ended_at == _dt("2026-07-13T21:01:39")


def test_compare_operations_reports_missing_extra_and_signal_id_mismatch():
    session = _dt("2026-07-03T10:13:36")
    actual = [
        ReplayOperation("BTCUSDT", 100, "SHORT", "1", session),
        ReplayOperation("BTCUSDT", 200, "CLOSE", None, session),
    ]
    expected = [
        ReplayOperation("BTCUSDT", 100, "SHORT", "2", session),
        ReplayOperation("BTCUSDT", 300, "CLOSE", None, session),
    ]

    diff = compare_operations(actual, expected)

    assert diff.matched == 1
    assert [item.open_time for item in diff.live_only] == [200]
    assert [item.open_time for item in diff.replay_only] == [300]
    assert diff.signal_event_id_mismatches == [
        {"symbol": "BTCUSDT", "open_time": 100, "operation_type": "SHORT", "actual": "1", "expected": "2"}
    ]


def test_validate_market_data_rejects_incomplete_hourly_coverage():
    def kline(open_time: int) -> Kline:
        return Kline(open_time, 1, 1, 1, 1, open_time + 3599, 1, 1, 1, 1, 1)

    rows = [kline(BASE) for BASE in (100, 3700, 10900)]

    try:
        validate_market_data("BTCUSDT", rows, 100, 10900)
    except ValueError as exc:
        assert "incomplete coverage" in str(exc)
    else:
        raise AssertionError("gap must fail the reconciliation coverage gate")


def test_execution_audit_counts_repeated_signal_ids_per_task_operation():
    session = _dt("2026-07-03T10:13:36")
    evidence = RuntimeEvidence(
        operations=[
            ReplayOperation("BTCUSDT", 100, "SHORT", "1", session),
            ReplayOperation("ETHUSDT", 100, "SHORT", "1", session),
            ReplayOperation("DOGEUSDT", 100, "LONG", None, session),
        ],
        audits=[
            ExecutionAudit("BTCUSDT", 1, session, "SHORT", "1", "a", "submitted", None),
            ExecutionAudit("ETHUSDT", 2, session, "SHORT", "1", "b", "submitted", None),
        ],
    )

    assert summarize_execution_audit(evidence) == {
        "entry_operations": 3,
        "audited_entry_outcomes": 2,
        "unaudited_entry_outcomes": 1,
        "status_counts": {"submitted": 2},
    }
