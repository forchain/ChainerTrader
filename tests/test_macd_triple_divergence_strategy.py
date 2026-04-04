from datetime import datetime
from pathlib import Path

import backtrader as bt

from trader.exchange.binance.csvdata import BinanceCSVData
from trader.strategy.macd_triple_divergence import MacdTripleDivergenceStrategy, SegmentSign


class _SignalProbeStrategy(MacdTripleDivergenceStrategy):
    params = (("chainer_auto_signal", False),)

    def __init__(self):
        super().__init__()
        self.long_dates = []
        self.short_dates = []

    def log_info(self, msg):
        pass

    def log_debug(self, msg):
        pass

    def next(self):
        self._update_segments()

        if self.get_long_signal():
            self.long_dates.append(self.cur_datetime().strftime("%Y-%m-%d"))

        if self.get_short_signal():
            self.short_dates.append(self.cur_datetime().strftime("%Y-%m-%d"))


def _run_probe():
    csv_path = Path(__file__).resolve().parents[1] / "data" / "BTCUSDT-1d-20170101-20251231.csv"
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(_SignalProbeStrategy)
    cerebro.adddata(BinanceCSVData(dataname=str(csv_path)))
    strategies = cerebro.run()
    return strategies[0]


def test_signal_dates_cover_documented_bottom_cases():
    st = _run_probe()

    expected = {
        "2018-02-03",
        "2018-02-06",
        "2018-06-25",
        "2019-12-18",
        "2023-06-06",
        "2023-06-15",
        "2024-05-03",
        "2025-04-09",
    }

    assert expected.issubset(set(st.long_dates))


def test_signal_dates_cover_documented_top_cases():
    st = _run_probe()

    expected = {
        "2021-04-16",
        "2020-02-10",
        "2020-02-13",
        "2020-06-02",
        "2024-01-11",
        "2024-10-31",
        "2025-05-23",
    }

    assert expected.issubset(set(st.short_dates))


def test_same_structure_does_not_emit_duplicate_signal_days():
    st = _run_probe()

    assert len(st.long_dates) == len(set(st.long_dates))
    assert len(st.short_dates) == len(set(st.short_dates))

    long_pairs = list(zip(st.long_dates, st.long_dates[1:]))
    short_pairs = list(zip(st.short_dates, st.short_dates[1:]))

    assert all((datetime.fromisoformat(right) - datetime.fromisoformat(left)).days > 1 for left, right in long_pairs)
    assert all((datetime.fromisoformat(right) - datetime.fromisoformat(left)).days > 1 for left, right in short_pairs)


def test_2018_02_06_bottom_divergence_only_triggers_once():
    st = _run_probe()

    assert "2018-02-06" in st.long_dates
    assert "2018-02-08" not in st.long_dates
    assert "2018-02-10" not in st.long_dates


def test_2018_06_25_bottom_divergence_does_not_retrigger_without_new_price_low():
    st = _run_probe()

    assert "2018-06-25" in st.long_dates
    assert "2018-06-27" not in st.long_dates
    assert "2018-06-29" not in st.long_dates


def test_2019_12_18_remains_valid():
    st = _run_probe()

    assert "2019-12-18" in st.long_dates


def test_2018_01_30_top_divergence_is_not_built_by_skipping_price_advancing_legs():
    st = _run_probe()

    assert "2018-01-30" not in st.short_dates


def test_2021_04_16_remains_valid_after_internal_weak_waves_are_filtered():
    st = _run_probe()

    assert "2021-04-16" in st.short_dates


def test_2018_04_02_bottom_divergence_is_blocked_by_stronger_intermediate_wave():
    st = _run_probe()

    assert "2018-04-02" not in st.long_dates


def test_2018_12_09_bottom_divergence_is_rejected_when_it_needs_more_than_five_same_sign_waves():
    st = _run_probe()

    assert "2018-12-09" not in st.long_dates


def test_2023_05_26_bottom_divergence_is_rejected_when_middle_same_sign_wave_does_not_form_valid_divergence_chain():
    st = _run_probe()

    assert "2023-05-26" not in st.long_dates


def test_2023_06_06_bottom_divergence_remains_valid_when_non_advancing_near_zero_split_is_ignored():
    st = _run_probe()

    assert "2023-06-06" in st.long_dates


def test_2023_06_15_bottom_divergence_remains_valid_after_invalid_internal_split_is_filtered_out():
    st = _run_probe()

    assert "2023-06-15" in st.long_dates


def test_2023_06_13_bottom_divergence_is_rejected_when_third_leg_does_not_beat_adjacent_green_separator_low():
    st = _run_probe()

    assert "2023-06-13" not in st.long_dates
    assert "2023-06-15" in st.long_dates


def test_2019_01_30_bottom_divergence_is_rejected_when_middle_leg_does_not_own_the_new_price_low():
    st = _run_probe()

    assert "2019-01-30" not in st.long_dates


def test_2019_05_06_top_divergence_is_rejected_when_selected_window_contains_more_than_five_raw_same_sign_waves():
    st = _run_probe()

    assert "2019-05-06" not in st.short_dates


def test_2019_11_25_bottom_divergence_is_rejected_when_filtered_waves_are_not_contiguous():
    st = _run_probe()

    assert "2019-11-25" not in st.long_dates


def test_2025_05_19_top_divergence_is_rejected_when_latest_leg_is_too_weak_to_trigger():
    st = _run_probe()

    assert "2025-05-19" not in st.short_dates
    assert "2025-05-23" in st.short_dates


def test_latest_same_sign_wave_window_is_capped_at_five():
    st = _run_probe()

    waves = st._build_recent_waves()
    for sign in (SegmentSign.NEGATIVE, SegmentSign.POSITIVE):
        latest = st._latest_same_sign_waves(waves, sign)
        assert len(latest) <= 5
