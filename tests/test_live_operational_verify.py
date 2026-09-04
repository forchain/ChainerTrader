from pathlib import Path

from trader.tools.live_operational_verify import verify_log


def _write_log(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "live.log"
    path.write_text(text, encoding="utf-8")
    return path


def _status(checks):
    return {check.name: check.passed for check in checks}


def test_operational_verify_rejects_startup_only_log_without_minute_fetch_or_tick(tmp_path):
    log_path = _write_log(
        tmp_path,
        "\n".join(
            [
                "2026-05-11 01:45:48,689[INFO:trader] Startup self-check: PASS exchange_connected=True",
                "2026-05-11 01:45:49,316[INFO:trader] Realtime startup backfill started: task_id=1 collection=BTCUSDT-1m stream=btcusdt@kline_1m kind=none limit=0 missing_count=0",
                "2026-05-11 01:45:49,316[INFO:trader] Realtime startup backfill completed: task_id=1 collection=BTCUSDT-1m stream=btcusdt@kline_1m fetched=0",
                "2026-05-11 01:45:49,316[INFO:trader] Realtime live warmup ready: collection=BTCUSDT-1m candles=500/500",
                "2026-05-11 01:45:49,344[INFO:root] CCXT polling scheduler stream registered: stream=btcusdt@kline_1m min_request_spacing_seconds=10.0",
                "2026-05-11 01:45:49,355[INFO:root] CCXT polling scheduler started: min_request_spacing_seconds=10.0",
                "2026-05-11 01:45:49,355[INFO:trader] Realtime stream subscribed: task_id=1 stream=btcusdt@kline_1m",
                "2026-05-11 01:45:49,355[INFO:trader] Realtime waiting for next closed kline: task_id=1 stream=btcusdt@kline_1m",
            ]
        ),
    )

    checks = verify_log(log_path, min_request_spacing_seconds=10.0)

    status = _status(checks)
    assert status["minute_stream_seen"] is True
    assert status["minute_fetch_seen"] is False
    assert status["realtime_strategy_tick_completed"] is False


def test_operational_verify_accepts_full_minute_runtime_chain(tmp_path):
    log_path = _write_log(
        tmp_path,
        "\n".join(
            [
                "2026-05-11 01:45:48,689[INFO:trader] Startup self-check: PASS exchange_connected=True",
                "2026-05-11 01:45:49,316[INFO:trader] Realtime startup backfill started: task_id=1 collection=BTCUSDT-1m stream=btcusdt@kline_1m kind=none limit=0 missing_count=0",
                "2026-05-11 01:45:49,316[INFO:trader] Realtime startup backfill completed: task_id=1 collection=BTCUSDT-1m stream=btcusdt@kline_1m fetched=0",
                "2026-05-11 01:45:49,316[INFO:trader] Realtime live warmup ready: collection=BTCUSDT-1m candles=500/500",
                "2026-05-11 01:45:49,344[INFO:root] CCXT polling scheduler stream registered: stream=btcusdt@kline_1m min_request_spacing_seconds=10.0",
                "2026-05-11 01:45:49,355[INFO:root] CCXT polling scheduler started: min_request_spacing_seconds=10.0",
                "2026-05-11 01:45:49,355[INFO:trader] Realtime stream subscribed: task_id=1 stream=btcusdt@kline_1m",
                "2026-05-11 01:45:49,355[INFO:trader] Realtime waiting for next closed kline: task_id=1 stream=btcusdt@kline_1m",
                "2026-05-11 01:45:59,356[INFO:root] CCXT polling fetch started: stream=btcusdt@kline_1m reason=interval_due",
                "2026-05-11 01:46:09,356[INFO:root] CCXT polling fetch started: stream=ethusdt@kline_1d reason=interval_due",
                "2026-05-11 01:46:59,355[DEBUG:trader] Realtime kline accepted: task_id=1 collection=BTCUSDT-1m stream=btcusdt@kline_1m open_time=1778435100 close_time=1778435159 close=101",
                "2026-05-11 01:46:59,356[DEBUG:trader] Realtime kline persisted: task_id=1 collection=BTCUSDT-1m stream=btcusdt@kline_1m open_time=1778435100 rows=1",
                "2026-05-11 01:46:59,357[DEBUG:trader] Realtime strategy tick completed: task_id=1 strategy=macd_triple_divergence stream=btcusdt@kline_1m open_time=1778435100 operations=0 op_types=[] mode=manual_notify",
            ]
        ),
    )

    checks = verify_log(log_path, min_request_spacing_seconds=10.0)

    assert all(check.passed for check in checks), [check.line() for check in checks]
