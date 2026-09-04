from trader.live.market_data import (
    BackfillRequestKind,
    KlineUpdateBuffer,
    KlineUpdateError,
    normalize_binance_kline_message,
    plan_initial_backfill,
)
from trader.utils.kline import Kline
from trader.utils.symbol_interval import Interval

BASE = 1_714_281_600


def test_backfill_plan_fetches_latest_500_when_database_has_no_history():
    plan = plan_initial_backfill(None, now=BASE + 123, interval=Interval.INTERVAL_1m)

    assert plan.kind == BackfillRequestKind.LATEST
    assert plan.limit == 500
    assert plan.missing_count == 500
    assert plan.start_time is None
    assert plan.end_time is None
    assert plan.truncated is False


def test_backfill_plan_fetches_exact_100_missing_closed_candles():
    latest = Kline(BASE, 1, 1, 1, 1, BASE + 59, 0, 0, 0, 0, 0)
    now = BASE + (101 * 60) + 30

    plan = plan_initial_backfill(latest, now=now, interval=Interval.INTERVAL_1m)

    assert plan.kind == BackfillRequestKind.RANGE
    assert plan.limit == 100
    assert plan.missing_count == 100
    assert plan.start_time == BASE + 60
    assert plan.end_time == BASE + (100 * 60)
    assert plan.truncated is False


def test_backfill_plan_truncates_over_500_missing_candles_to_latest_window():
    latest = Kline(BASE, 1, 1, 1, 1, BASE + 59, 0, 0, 0, 0, 0)
    now = BASE + (700 * 60) + 1

    plan = plan_initial_backfill(latest, now=now, interval=Interval.INTERVAL_1m)

    assert plan.kind == BackfillRequestKind.LATEST
    assert plan.limit == 500
    assert plan.missing_count == 699
    assert plan.truncated is True
    assert "500" in plan.diagnostic


def test_backfill_plan_does_not_fetch_when_database_is_current():
    latest = Kline(BASE + 60, 1, 1, 1, 1, BASE + 119, 0, 0, 0, 0, 0)
    now = BASE + 120

    plan = plan_initial_backfill(latest, now=now, interval=Interval.INTERVAL_1m)

    assert plan.kind == BackfillRequestKind.NONE
    assert plan.limit == 0
    assert plan.missing_count == 0


def _binance_payload(is_closed: bool = False, open_time_ms: int = BASE * 1000) -> dict:
    return {
        "e": "kline",
        "E": (BASE + 10) * 1000,
        "s": "BTCUSDT",
        "k": {
            "t": open_time_ms,
            "T": open_time_ms + 59_999,
            "s": "BTCUSDT",
            "i": "1m",
            "o": "100.0",
            "c": "101.0",
            "h": "102.0",
            "l": "99.0",
            "v": "12.5",
            "n": 42,
            "x": is_closed,
            "q": "1262.5",
            "V": "6.0",
            "Q": "606.0",
            "B": "0",
        },
    }


def test_normalize_binance_open_kline_payload():
    update = normalize_binance_kline_message(_binance_payload(is_closed=False), exchange="BINANCE")

    assert update.exchange == "BINANCE"
    assert update.symbol == "BTCUSDT"
    assert update.interval == "1m"
    assert update.open_time == BASE
    assert update.close_time == BASE + 59
    assert update.event_time == BASE + 10
    assert update.open == 100.0
    assert update.high == 102.0
    assert update.low == 99.0
    assert update.close == 101.0
    assert update.volume == 12.5
    assert update.is_closed is False


def test_normalize_binance_closed_kline_payload_can_be_converted_to_db_kline():
    update = normalize_binance_kline_message(_binance_payload(is_closed=True), exchange="BINANCE")
    kline = update.to_kline()

    assert update.is_closed is True
    assert kline.open_time == BASE
    assert kline.close_time == BASE + 59
    assert kline.close == 101.0
    assert kline.trades == 42


def test_normalize_binance_payload_requires_closed_flag():
    payload = _binance_payload()
    del payload["k"]["x"]

    try:
        normalize_binance_kline_message(payload)
    except KlineUpdateError as exc:
        assert "closed" in str(exc)
    else:
        raise AssertionError("expected KlineUpdateError")


def test_kline_update_buffer_rejects_duplicates_and_stale_open_updates():
    buffer = KlineUpdateBuffer()
    open_update = normalize_binance_kline_message(_binance_payload(is_closed=False))
    closed_update = normalize_binance_kline_message(_binance_payload(is_closed=True))
    next_open = normalize_binance_kline_message(_binance_payload(is_closed=False, open_time_ms=(BASE + 60) * 1000))

    assert buffer.accept(open_update) is True
    assert buffer.accept(open_update) is True
    assert buffer.accept(closed_update) is True
    assert buffer.accept(closed_update) is False
    assert buffer.accept(open_update) is False
    assert buffer.accept(next_open) is True
