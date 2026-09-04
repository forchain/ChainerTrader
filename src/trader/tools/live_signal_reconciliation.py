from __future__ import annotations

import argparse
import ast
import json
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import requests

from trader.common.config import Config
from trader.common.logger import Logger
from trader.live.backtrader_runtime import BacktraderLiveRunner
from trader.strategy.macd_triple_divergence import MacdTripleDivergenceStrategy
from trader.strategy.node import build_strategy_kwargs
from trader.utils.kline import Kline

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
INTERVAL_SECONDS = 3600

_LOG_TIME = r"(?P<log_time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
_SESSION_RE = re.compile(
    rf"^{_LOG_TIME},\d+.*Realtime live warmup started: task_id=(?P<task_id>\d+) "
    r"collection=(?P<symbol>[A-Z0-9]+)-1h target=(?P<target>\d+)"
)
_OPERATION_RE = re.compile(
    rf"^{_LOG_TIME},\d+.*Realtime strategy signal: task_id=(?P<task_id>\d+).*"
    r"stream=(?P<symbol>[a-z0-9]+)@kline_1h open_time=(?P<open_time>\d+).*"
    r"op_types=\[(?P<operation_type>[^]]+)\].*execution_outcomes=(?P<outcomes>\d+)"
)
_AUDIT_RE = re.compile(
    rf"^{_LOG_TIME},\d+.*\[auto_execution\] (?P<label>submitted|failed|margin_borrow_blocked) "
    r"(?P<payload>\{.*\})$"
)
_STREAM_REMOVED_RE = re.compile(
    rf"^{_LOG_TIME},\d+.*CCXT polling scheduler stream removed: stream=(?P<symbol>[a-z0-9]+)@kline_1h"
)
_STREAM_REGISTERED_RE = re.compile(
    rf"^{_LOG_TIME},\d+.*CCXT polling scheduler stream registered: stream=(?P<symbol>[a-z0-9]+)@kline_1h"
)


@dataclass(frozen=True)
class RuntimeSession:
    symbol: str
    task_id: int
    started_at: datetime
    target: int


@dataclass(frozen=True)
class ReplayOperation:
    symbol: str
    open_time: int
    operation_type: str
    signal_event_id: str | None
    session_started_at: datetime


@dataclass(frozen=True)
class ExecutionAudit:
    symbol: str
    task_id: int
    logged_at: datetime
    operation_type: str
    signal_event_id: str | None
    order_id: str | None
    status: str
    reason: str | None


@dataclass(frozen=True)
class RuntimeOutage:
    symbol: str
    started_at: datetime
    ended_at: datetime


@dataclass
class RuntimeEvidence:
    sessions: dict[str, list[RuntimeSession]] = field(default_factory=dict)
    operations: list[ReplayOperation] = field(default_factory=list)
    audits: list[ExecutionAudit] = field(default_factory=list)
    outages: dict[str, list[RuntimeOutage]] = field(default_factory=dict)


@dataclass
class OperationDiff:
    matched: int
    live_only: list[ReplayOperation]
    replay_only: list[ReplayOperation]
    signal_event_id_mismatches: list[dict]


def _parse_log_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)


def _signal_id(operation_id: object) -> str | None:
    text = str(operation_id or "")
    prefix = "signal_event_id:"
    return text[len(prefix) :] if text.startswith(prefix) else None


def parse_runtime_evidence(text: str, start: datetime, end: datetime) -> RuntimeEvidence:
    sessions: dict[str, list[RuntimeSession]] = {}
    operations_with_log_time: list[tuple[datetime, ReplayOperation]] = []
    audits: list[ExecutionAudit] = []
    outages: dict[str, list[RuntimeOutage]] = {}
    open_outages: dict[str, datetime] = {}

    for line in text.splitlines():
        if match := _SESSION_RE.search(line):
            logged_at = _parse_log_time(match.group("log_time"))
            if start <= logged_at <= end:
                symbol = match.group("symbol").upper()
                sessions.setdefault(symbol, []).append(
                    RuntimeSession(symbol, int(match.group("task_id")), logged_at, int(match.group("target")))
                )
            continue
        if match := _STREAM_REMOVED_RE.search(line):
            logged_at = _parse_log_time(match.group("log_time"))
            if start <= logged_at <= end:
                open_outages.setdefault(match.group("symbol").upper(), logged_at)
            continue
        if match := _STREAM_REGISTERED_RE.search(line):
            logged_at = _parse_log_time(match.group("log_time"))
            symbol = match.group("symbol").upper()
            if symbol in open_outages and start <= logged_at <= end:
                outages.setdefault(symbol, []).append(RuntimeOutage(symbol, open_outages.pop(symbol), logged_at))
            continue
        if match := _AUDIT_RE.search(line):
            logged_at = _parse_log_time(match.group("log_time"))
            if not start <= logged_at <= end:
                continue
            payload = ast.literal_eval(match.group("payload"))
            audits.append(
                ExecutionAudit(
                    str(payload["market"]).upper(),
                    int(payload["task_id"]),
                    logged_at,
                    str(payload["operation_type"]),
                    _signal_id(payload.get("operation_id")),
                    str(payload.get("order_id")) if payload.get("order_id") else None,
                    str(payload.get("status") or match.group("label")),
                    str(payload.get("reason")) if payload.get("reason") else None,
                )
            )
            continue
        if match := _OPERATION_RE.search(line):
            logged_at = _parse_log_time(match.group("log_time"))
            if not start <= logged_at <= end or int(match.group("outcomes")) <= 0:
                continue
            symbol = match.group("symbol").upper()
            operations_with_log_time.append(
                (
                    logged_at,
                    ReplayOperation(
                        symbol,
                        int(match.group("open_time")),
                        match.group("operation_type"),
                        None,
                        logged_at,
                    ),
                )
            )

    for rows in sessions.values():
        rows.sort(key=lambda item: item.started_at)
    for symbol, started_at in open_outages.items():
        outages.setdefault(symbol, []).append(RuntimeOutage(symbol, started_at, end))

    operations: list[ReplayOperation] = []
    for logged_at, operation in operations_with_log_time:
        candidates = [item for item in sessions.get(operation.symbol, []) if item.started_at <= logged_at]
        session_started_at = candidates[-1].started_at if candidates else logged_at
        submission = next(
            (
                item
                for item in reversed(audits)
                if item.symbol == operation.symbol
                and item.operation_type == operation.operation_type
                and item.status == "submitted"
                and 0 <= (logged_at - item.logged_at).total_seconds() <= 30
            ),
            None,
        )
        operations.append(
            ReplayOperation(
                operation.symbol,
                operation.open_time,
                operation.operation_type,
                submission.signal_event_id if submission else None,
                session_started_at,
            )
        )
    return RuntimeEvidence(sessions, operations, audits, outages)


def compare_operations(actual: list[ReplayOperation], expected: list[ReplayOperation]) -> OperationDiff:
    def key(item: ReplayOperation) -> tuple[str, int, str]:
        return item.symbol, item.open_time, item.operation_type

    actual_counts = Counter(key(item) for item in actual)
    expected_counts = Counter(key(item) for item in expected)
    matched = sum((actual_counts & expected_counts).values())
    live_only_counts = actual_counts - expected_counts
    replay_only_counts = expected_counts - actual_counts
    live_only = []
    for item in actual:
        item_key = key(item)
        if live_only_counts[item_key] > 0:
            live_only.append(item)
            live_only_counts[item_key] -= 1
    replay_only = []
    for item in expected:
        item_key = key(item)
        if replay_only_counts[item_key] > 0:
            replay_only.append(item)
            replay_only_counts[item_key] -= 1

    actual_by_key = {key(item): item for item in actual}
    expected_by_key = {key(item): item for item in expected}
    id_mismatches = []
    for shared_key in sorted(actual_counts.keys() & expected_counts.keys()):
        actual_id = actual_by_key[shared_key].signal_event_id
        expected_id = expected_by_key[shared_key].signal_event_id
        if actual_id is not None and expected_id is not None and actual_id != expected_id:
            id_mismatches.append(
                {
                    "symbol": shared_key[0],
                    "open_time": shared_key[1],
                    "operation_type": shared_key[2],
                    "actual": actual_id,
                    "expected": expected_id,
                }
            )
    return OperationDiff(matched, live_only, replay_only, id_mismatches)


def summarize_execution_audit(evidence: RuntimeEvidence) -> dict:
    entry_operations = [item for item in evidence.operations if item.operation_type in {"LONG", "SHORT"}]
    audited_entry_outcomes = sum(
        1 for item in evidence.audits if item.operation_type in {"LONG", "SHORT"} and item.signal_event_id is not None
    )
    return {
        "entry_operations": len(entry_operations),
        "audited_entry_outcomes": audited_entry_outcomes,
        "unaudited_entry_outcomes": len(entry_operations) - audited_entry_outcomes,
        "status_counts": dict(Counter(item.status for item in evidence.audits)),
    }


def _request_klines(symbol: str, start_open_time: int, end_open_time: int) -> list[Kline]:
    response = requests.get(
        "https://api.binance.com/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": "1h",
            "startTime": start_open_time * 1000,
            "endTime": (end_open_time + INTERVAL_SECONDS) * 1000 - 1,
            "limit": 1000,
        },
        timeout=30,
    )
    response.raise_for_status()
    return [
        Kline(
            int(row[0] // 1000),
            float(row[1]),
            float(row[2]),
            float(row[3]),
            float(row[4]),
            int(row[6] // 1000),
            float(row[5]),
            float(row[7]),
            int(row[8]),
            float(row[9]),
            float(row[10]),
            float(row[11]),
        )
        for row in response.json()
    ]


def fetch_market_data(symbols: Iterable[str], start_open_time: int, end_open_time: int) -> dict[str, list[Kline]]:
    result = {}
    for symbol in symbols:
        rows = []
        cursor = start_open_time
        while cursor <= end_open_time:
            last_error = None
            for attempt in range(3):
                try:
                    page = _request_klines(symbol, cursor, end_open_time)
                    break
                except requests.RequestException as exc:
                    last_error = exc
                    time.sleep(2**attempt)
            else:
                raise RuntimeError(f"failed to fetch public Binance klines for {symbol}: {last_error}")
            if not page:
                break
            rows.extend(page)
            next_cursor = page[-1].open_time + INTERVAL_SECONDS
            if next_cursor <= cursor:
                raise RuntimeError(f"Binance kline pagination did not advance for {symbol}")
            cursor = next_cursor
        validate_market_data(symbol, rows, start_open_time, end_open_time)
        result[symbol] = rows
    return result


def validate_market_data(symbol: str, rows: list[Kline], start_open_time: int, end_open_time: int) -> None:
    expected = list(range(start_open_time, end_open_time + INTERVAL_SECONDS, INTERVAL_SECONDS))
    actual = [item.open_time for item in rows]
    if actual != expected:
        raise ValueError(
            f"incomplete coverage for {symbol}: expected {len(expected)} hourly candles "
            f"from {start_open_time} through {end_open_time}, got {len(actual)}"
        )


def _wait_until(predicate, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise TimeoutError("live replay did not consume all supplied klines")


def replay_session(
    session: RuntimeSession,
    session_end: datetime,
    klines: list[Kline],
    strategy_params: dict,
    outages: list[RuntimeOutage] | None = None,
) -> list[ReplayOperation]:
    started_ts = int(session.started_at.timestamp())
    ended_ts = int(session_end.timestamp())
    closed_before_start = [item for item in klines if item.close_time <= started_ts]
    warmup = closed_before_start[-session.target :]
    live = [item for item in klines if started_ts < item.close_time <= ended_ts]
    if outages:
        live = [
            item
            for item in live
            if not any(
                int(outage.started_at.timestamp()) < item.close_time <= int(outage.ended_at.timestamp())
                for outage in outages
            )
        ]
    captured = []
    cfg = Config(log_level="ERROR", log_file=False, api=None, cash=10000.0)
    logger = Logger(cfg, 1000, True)
    runner = BacktraderLiveRunner(
        [MacdTripleDivergenceStrategy],
        cash=10000.0,
        commission=0.001,
        qcheck=0.001,
        strategy_kwargs=build_strategy_kwargs(cfg, logger, 0.0, True, strategy_params),
        operation_handler=captured.append,
        inject_operation_sink=True,
    )
    runner.start(warmup=warmup)
    try:
        if warmup:
            _wait_until(lambda: runner.status()["latest_processed_open_time"] == warmup[-1].open_time)
        for kline in live:
            runner.put_kline(kline)
            _wait_until(lambda: runner.status()["latest_processed_open_time"] == kline.open_time)
    finally:
        runner.stop()
    return [
        ReplayOperation(
            session.symbol,
            int(op.dtime),
            op.otype.name,
            str(getattr(op, "signal_event_id", "")) or None,
            session.started_at,
        )
        for op in captured
        if getattr(op, "feed_phase", None) == "live" and op.otype.name != "RISK_UPDATE"
    ]


def replay_sessions(
    sessions: dict[str, list[RuntimeSession]],
    market_data: dict[str, list[Kline]],
    end: datetime,
    strategy_params: dict,
    continuous: bool,
    respect_outages: bool = False,
    outages: dict[str, list[RuntimeOutage]] | None = None,
) -> list[ReplayOperation]:
    operations = []
    outages = outages or {}
    for symbol, symbol_sessions in sorted(sessions.items()):
        selected = symbol_sessions[:1] if continuous else symbol_sessions
        for index, session in enumerate(selected):
            session_end = end
            if not continuous and index + 1 < len(symbol_sessions):
                session_end = symbol_sessions[index + 1].started_at
            symbol_outages = outages.get(symbol, []) if respect_outages else []
            operations.extend(replay_session(session, session_end, market_data[symbol], strategy_params, symbol_outages))
    return operations


def _json_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _parse_local(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=LOCAL_TZ)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile July live MACD operations with offline replay.")
    parser.add_argument("--log", default="logs/trader.log")
    parser.add_argument("--task-config", default="configs/tasks/live/auto_trade_macd_triple_divergence_top10_production.json")
    parser.add_argument("--start", default="2026-07-01T00:00:00")
    parser.add_argument("--end", default="2026-07-14T16:01:25")
    parser.add_argument("--data-start", default="2026-06-10T00:00:00")
    parser.add_argument("--output", default="tmp/2026-07-live-signal-reconciliation.json")
    args = parser.parse_args()

    start = _parse_local(args.start)
    end = _parse_local(args.end)
    evidence = parse_runtime_evidence(Path(args.log).read_text(encoding="utf-8"), start, end)
    task_config = json.loads(Path(args.task_config).read_text(encoding="utf-8"))
    symbols = [str(item["symbol"]).replace("-", "").upper() for item in task_config]
    strategy_params = dict(task_config[0]["strategy_params"])
    data_start = int(_parse_local(args.data_start).timestamp())
    end_open_time = int(end.timestamp()) // INTERVAL_SECONDS * INTERVAL_SECONDS - INTERVAL_SECONDS
    market_data = fetch_market_data(symbols, data_start, end_open_time)
    coverage = {
        symbol: {
            "count": len(rows),
            "first_open_time": rows[0].open_time if rows else None,
            "last_open_time": rows[-1].open_time if rows else None,
            "gaps": sum(1 for left, right in zip(rows, rows[1:]) if right.open_time - left.open_time != INTERVAL_SECONDS),
        }
        for symbol, rows in market_data.items()
    }
    continuous = replay_sessions(evidence.sessions, market_data, end, strategy_params, continuous=True)
    restart_ideal = replay_sessions(evidence.sessions, market_data, end, strategy_params, continuous=False)
    faithful = replay_sessions(
        evidence.sessions,
        market_data,
        end,
        strategy_params,
        continuous=False,
        respect_outages=True,
        outages=evidence.outages,
    )
    payload = {
        "window": {"start": start, "end": end, "end_open_time": end_open_time},
        "coverage": coverage,
        "actual": evidence,
        "continuous_replay": continuous,
        "restart_ideal_delivery_replay": restart_ideal,
        "restart_faithful_replay": faithful,
        "continuous_diff": compare_operations(evidence.operations, continuous),
        "restart_ideal_delivery_diff": compare_operations(evidence.operations, restart_ideal),
        "restart_faithful_diff": compare_operations(evidence.operations, faithful),
        "execution_audit": summarize_execution_audit(evidence),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_json_value(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
