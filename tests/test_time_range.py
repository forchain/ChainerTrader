from datetime import datetime, timedelta

from trader.common.time_range import (
    offset_time_backward,
    parse_relative_duration,
    resolve_time_range,
)


def test_parse_relative_duration():
    assert parse_relative_duration("1y") == (1, "y")
    assert parse_relative_duration("-1y") == (1, "y")
    assert parse_relative_duration("1Y") == (1, "y")
    assert parse_relative_duration("365d") == (365, "d")
    assert parse_relative_duration("30D") == (30, "d")
    assert parse_relative_duration("-30d") == (30, "d")
    assert parse_relative_duration("6m") == (6, "m")
    assert parse_relative_duration("2w") == (2, "w")
    assert parse_relative_duration("24h") == (24, "h")

    # Non-relative strings
    assert parse_relative_duration("2026-04-30 00:00:00") is None
    assert parse_relative_duration("1714435200") is None
    assert parse_relative_duration("") is None
    assert parse_relative_duration(None) is None
    assert parse_relative_duration("1year") is None
    assert parse_relative_duration("abc") is None


def test_offset_time_backward():
    anchor = datetime(2026, 9, 4, 12, 0, 0)

    # 1 year backward
    assert offset_time_backward(anchor, 1, "y") == datetime(2025, 9, 4, 12, 0, 0)
    # 6 months backward
    assert offset_time_backward(anchor, 6, "m") == datetime(2026, 3, 4, 12, 0, 0)
    # 2 weeks backward
    assert offset_time_backward(anchor, 2, "w") == datetime(2026, 8, 21, 12, 0, 0)
    # 30 days backward
    assert offset_time_backward(anchor, 30, "d") == datetime(2026, 8, 5, 12, 0, 0)
    # 24 hours backward
    assert offset_time_backward(anchor, 24, "h") == datetime(2026, 9, 3, 12, 0, 0)


def test_offset_time_backward_month_end_clamping():
    # March 31 minus 1 month should clamp to February 28 (non-leap year 2025)
    anchor = datetime(2025, 3, 31, 0, 0, 0)
    assert offset_time_backward(anchor, 1, "m") == datetime(2025, 2, 28, 0, 0, 0)

    # March 31 minus 1 month in leap year 2024 should clamp to February 29
    anchor_leap = datetime(2024, 3, 31, 0, 0, 0)
    assert offset_time_backward(anchor_leap, 1, "m") == datetime(2024, 2, 29, 0, 0, 0)


def test_resolve_time_range_relative_start_time():
    now = datetime(2026, 9, 4, 12, 0, 0)

    # start_time="1y", end_time omitted (defaults to now)
    start_ts, end_ts = resolve_time_range("1y", None, now=now)
    assert end_ts == int(now.timestamp())
    expected_start = datetime(2025, 9, 4, 12, 0, 0)
    assert start_ts == int(expected_start.timestamp())

    # start_time="365d"
    start_ts_365, end_ts_365 = resolve_time_range("365d", None, now=now)
    assert end_ts_365 == int(now.timestamp())
    assert start_ts_365 == int((now - timedelta(days=365)).timestamp())


def test_resolve_time_range_relative_start_with_fixed_end():
    fixed_end = "2026-06-01 00:00:00"
    fixed_end_dt = datetime(2026, 6, 1, 0, 0, 0)

    start_ts, end_ts = resolve_time_range("1y", fixed_end)
    assert end_ts == int(fixed_end_dt.timestamp())
    expected_start = datetime(2025, 6, 1, 0, 0, 0)
    assert start_ts == int(expected_start.timestamp())


def test_resolve_time_range_relative_end_and_start():
    now = datetime(2026, 9, 4, 12, 0, 0)

    # end_time="1d", start_time="1w" (1 week before 1 day ago)
    start_ts, end_ts = resolve_time_range("1w", "1d", now=now)
    expected_end = datetime(2026, 9, 3, 12, 0, 0)
    expected_start = datetime(2026, 8, 27, 12, 0, 0)
    assert end_ts == int(expected_end.timestamp())
    assert start_ts == int(expected_start.timestamp())


def test_resolve_time_range_fixed_datetimes():
    start_str = "2025-01-01 00:00:00"
    end_str = "2026-01-01 00:00:00"
    start_ts, end_ts = resolve_time_range(start_str, end_str)

    assert start_ts == int(datetime(2025, 1, 1, 0, 0, 0).timestamp())
    assert end_ts == int(datetime(2026, 1, 1, 0, 0, 0).timestamp())


def test_resolve_time_range_defaults_when_empty():
    now = datetime(2026, 9, 4, 12, 0, 0)

    # Neither specified: start defaults to 2000-01-01, end defaults to now
    start_ts, end_ts = resolve_time_range(None, None, now=now)
    assert end_ts == int(now.timestamp())
    assert start_ts == int(datetime(2000, 1, 1, 0, 0, 0).timestamp())
