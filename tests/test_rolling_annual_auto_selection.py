from trader.tools.rolling_annual_auto_selection import _compounded_return_pct, monthly_windows


def test_monthly_windows_2025_are_calendar_aligned():
    windows = monthly_windows(2025)

    assert windows[0].month == "2025-01"
    assert windows[0].selection_start == "2024-01-01 00:00:00"
    assert windows[0].selection_end == "2025-01-01 00:00:00"
    assert windows[0].hold_start == "2025-01-01 00:00:00"
    assert windows[0].hold_end == "2025-02-01 00:00:00"

    assert windows[-1].month == "2025-12"
    assert windows[-1].selection_start == "2024-12-01 00:00:00"
    assert windows[-1].selection_end == "2025-12-01 00:00:00"
    assert windows[-1].hold_start == "2025-12-01 00:00:00"
    assert windows[-1].hold_end == "2026-01-01 00:00:00"


def test_compounded_return_pct():
    assert _compounded_return_pct([10.0, -5.0, 2.0]) == 6.59
