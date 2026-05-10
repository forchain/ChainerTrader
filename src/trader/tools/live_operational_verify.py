from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


LOG_TS_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+")
FETCH_RE = re.compile(r"CCXT polling fetch started: stream=(?P<stream>\S+)")


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""

    def line(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"{self.name}: {status}{(' ' + self.detail) if self.detail else ''}"


def verify_log(log_path: Path, *, min_request_spacing_seconds: float = 10.0) -> list[Check]:
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    lines = text.splitlines()
    checks: list[Check] = []

    checks.append(_contains(text, "startup_self_check", "Startup self-check: PASS"))
    checks.append(_contains(text, "ccxt_scheduler_active", "CCXT polling scheduler started"))
    checks.append(_contains(text, "ccxt_stream_registered", "CCXT polling scheduler stream registered"))
    checks.append(_contains(text, "realtime_backfill_started", "Realtime startup backfill started"))
    checks.append(_contains(text, "realtime_backfill_completed", "Realtime startup backfill completed"))
    checks.append(_contains(text, "realtime_warmup_ready", "Realtime live warmup ready"))
    checks.append(_contains(text, "realtime_stream_subscribed", "Realtime stream subscribed"))
    checks.append(_contains(text, "realtime_waiting_for_closed_kline", "Realtime waiting for next closed kline"))
    checks.append(_absent(text, "websocket_inactive", "Binance kline websocket"))
    checks.append(_absent(text, "legacy_per_stream_polling_inactive", "CCXT polling market stream started"))
    checks.append(_daily_stream_not_overpolled(lines))
    checks.append(_global_rate_limit(lines, min_request_spacing_seconds=min_request_spacing_seconds))
    checks.append(_minute_stream_seen(text))
    checks.append(_minute_fetch_seen(lines))
    checks.append(_minute_runtime_chain_seen(text))
    return checks


def _contains(text: str, name: str, needle: str) -> Check:
    return Check(name, needle in text, f"missing={needle!r}" if needle not in text else "")


def _absent(text: str, name: str, needle: str) -> Check:
    return Check(name, needle not in text, f"unexpected={needle!r}" if needle in text else "")


def _daily_stream_not_overpolled(lines: list[str]) -> Check:
    counts: dict[str, int] = {}
    for line in lines:
        match = FETCH_RE.search(line)
        if not match:
            continue
        stream = match.group("stream")
        if "@kline_1d" in stream:
            counts[stream] = counts.get(stream, 0) + 1
    offenders = {stream: count for stream, count in counts.items() if count > 1}
    if offenders:
        return Check("daily_stream_not_overpolled", False, f"offenders={offenders}")
    return Check("daily_stream_not_overpolled", True, f"daily_fetches={counts}" if counts else "daily_fetches=0")


def _global_rate_limit(lines: list[str], *, min_request_spacing_seconds: float) -> Check:
    events: list[tuple[datetime, str]] = []
    for line in lines:
        fetch = FETCH_RE.search(line)
        if not fetch:
            continue
        ts = LOG_TS_RE.search(line)
        if not ts:
            continue
        events.append((datetime.strptime(ts.group("ts"), "%Y-%m-%d %H:%M:%S"), fetch.group("stream")))
    if len(events) < 2:
        return Check("global_rate_limit", True, f"fetch_events={len(events)}")
    violations = []
    for (prev_ts, prev_stream), (cur_ts, cur_stream) in zip(events, events[1:], strict=False):
        delta = (cur_ts - prev_ts).total_seconds()
        if delta + 0.001 < min_request_spacing_seconds:
            violations.append(f"{prev_stream}->{cur_stream}:{delta:.1f}s")
    if violations:
        return Check("global_rate_limit", False, f"min={min_request_spacing_seconds}s violations={violations[:5]}")
    return Check("global_rate_limit", True, f"fetch_events={len(events)}")


def _minute_stream_seen(text: str) -> Check:
    if "@kline_1m" in text and "Realtime stream subscribed" in text:
        return Check("minute_stream_seen", True)
    return Check("minute_stream_seen", False, "missing subscribed 1m stream")


def _minute_fetch_seen(lines: list[str]) -> Check:
    streams = [match.group("stream") for line in lines if (match := FETCH_RE.search(line))]
    minute_streams = [stream for stream in streams if "@kline_1m" in stream]
    if minute_streams:
        return Check("minute_fetch_seen", True, f"minute_fetches={minute_streams}")
    return Check("minute_fetch_seen", False, "missing CCXT 1m fetch")


def _minute_runtime_chain_seen(text: str) -> Check:
    requirements = {
        "accepted": "Realtime kline accepted",
        "persisted": "Realtime kline persisted",
        "tick_completed": "Realtime strategy tick completed",
    }
    missing = [name for name, needle in requirements.items() if needle not in text or "@kline_1m" not in _lines_containing(text, needle)]
    if missing:
        return Check("realtime_strategy_tick_completed", False, f"missing_1m_chain={missing}")
    return Check("realtime_strategy_tick_completed", True)


def _lines_containing(text: str, needle: str) -> str:
    return "\n".join(line for line in text.splitlines() if needle in line)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify live operational readiness from a make serve log.")
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--min-request-spacing-seconds", type=float, default=10.0)
    args = parser.parse_args()

    checks = verify_log(args.log, min_request_spacing_seconds=args.min_request_spacing_seconds)
    passed = all(check.passed for check in checks)
    print(f"Operational verification: {'PASS' if passed else 'FAIL'}")
    print(f"log: {args.log}")
    for check in checks:
        print(check.line())
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
