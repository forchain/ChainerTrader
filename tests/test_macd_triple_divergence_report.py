from pathlib import Path

import backtrader as bt

from trader.analyzers.backtest_report import BacktestReportAnalyzer
from trader.exchange.binance.csvdata import BinanceCSVData
from trader.strategy.macd_triple_divergence import DEFAULT_NOISE_CLUSTER_RATIO, MacdTripleDivergenceStrategy


class _SilentReportStrategy(MacdTripleDivergenceStrategy):
    def log_info(self, msg):
        pass

    def log_debug(self, msg):
        pass


def _run_report_probe():
    csv_path = Path(__file__).resolve().parents[1] / "data" / "BTCUSDT-1d-20170101-20251231.csv"
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(_SilentReportStrategy)
    cerebro.adddata(BinanceCSVData(dataname=str(csv_path)))
    cerebro.addanalyzer(
        BacktestReportAnalyzer,
        _name="backtest_report",
        strategy_name="macd_triple_divergence",
        symbol="BTCUSDT",
        interval="1d",
    )
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.001)
    strategies = cerebro.run()
    return strategies[0].analyzers.backtest_report.report


def test_report_includes_signal_context_for_documented_top_case():
    report = _run_report_probe()

    signal = next(s for s in report["signals"] if s["signal_time"] == "2025-05-23T08:00:00")

    assert signal["is_documented_case"] is True
    assert signal["documented_case_status"] == "success"
    assert signal["signal_type"] == "top_divergence"
    assert len(signal["legs"]) == 3
    assert signal["conditions"]["price_higher_highs"]["passed"] is True
    assert signal["conditions"]["macd_lower_highs"]["passed"] is True
    assert signal["legs"][0]["price_on_macd_peak_bar"] < signal["legs"][1]["price_on_macd_peak_bar"] < signal["legs"][2]["price_on_macd_peak_bar"]
    assert signal["legs"][0]["macd_peak"] > signal["legs"][1]["macd_peak"] > signal["legs"][2]["macd_peak"]
    assert signal["legs"][0]["macd_half_strength"] is not None
    assert signal["legs"][0]["wave_price_high"] >= signal["legs"][0]["price_on_macd_peak_bar"]
    assert signal["legs"][1]["wave_price_high"] >= signal["legs"][1]["price_on_macd_peak_bar"]
    assert signal["legs"][2]["trigger_pivot_time"] is not None
    assert "selected_pivot" not in signal["legs"][2]
    assert "wave_pivots" not in signal["legs"][2]


def test_report_includes_near_zero_separator_details_and_blocked_trade_reason():
    report = _run_report_probe()

    near_zero_signal = next(s for s in report["signals"] if s["signal_time"] == "2024-05-03T08:00:00")
    near_zero_separators = [sep for sep in near_zero_signal["conditions"]["separator_details"] if sep["mode"] == "near_zero"]

    assert near_zero_signal["signal_type"] == "bottom_divergence"
    assert near_zero_separators
    assert near_zero_separators[0]["separator_ratio"] is not None
    assert near_zero_separators[0]["noise_cluster_ratio_threshold"] == DEFAULT_NOISE_CLUSTER_RATIO
    assert near_zero_separators[0]["from_time"] is not None
    assert near_zero_separators[0]["to_time"] is not None

    blocked_signal = next(s for s in report["signals"] if s["signal_time"] == "2025-05-23T08:00:00")
    assert blocked_signal["trade_outcome"]["status"] == "blocked_active_trade"
    assert blocked_signal["trade_outcome"]["active_trade"] is not None


def test_report_uses_time_based_separator_context_for_documented_2024_top_case():
    report = _run_report_probe()

    signal = next(s for s in report["signals"] if s["signal_time"] == "2024-01-11T08:00:00")
    sep = signal["conditions"]["separator_details"][0]

    assert signal["signal_type"] == "top_divergence"
    assert sep["mode"] in {"near_zero", "opposite_color"}
    assert sep["from_time"] == signal["legs"][0]["macd_peak_time"]
    assert sep["to_time"] == signal["legs"][1]["macd_peak_time"]
    assert sep["noise_cluster_ratio_threshold"] == DEFAULT_NOISE_CLUSTER_RATIO


def test_report_shows_2019_12_18_signal():
    report = _run_report_probe()

    assert any(s["signal_time"] == "2019-12-18T08:00:00" for s in report["signals"])


def test_report_shows_2023_06_06_and_2023_06_15_signals():
    report = _run_report_probe()

    signal_times = {signal["signal_time"] for signal in report["signals"]}

    assert "2023-06-06T08:00:00" in signal_times
    assert "2023-06-15T08:00:00" in signal_times


def test_report_includes_all_documented_cases_including_failed_examples():
    report = _run_report_probe()

    documented = report["documented_cases"]
    case_times = {case["case_time"] for case in documented}

    expected = {
        "2025-05-23T08:00:00",
        "2024-10-31T08:00:00",
        "2024-01-11T08:00:00",
        "2021-04-16T08:00:00",
        "2020-06-02T08:00:00",
        "2020-02-10T08:00:00",
        "2020-02-13T08:00:00",
        "2025-04-09T08:00:00",
        "2024-05-03T08:00:00",
        "2023-06-06T08:00:00",
        "2023-06-15T08:00:00",
        "2019-12-18T08:00:00",
        "2018-06-25T08:00:00",
        "2018-02-03T08:00:00",
        "2018-02-06T08:00:00",
    }

    assert expected.issubset(case_times)
    assert any(case["case_time"] == "2020-02-10T08:00:00" and case["case_status"] == "failed" for case in documented)
    assert any(case["case_time"] == "2023-06-06T08:00:00" and case["case_status"] == "failed" for case in documented)
    assert any(case["case_time"] == "2018-06-25T08:00:00" and case["case_status"] == "failed" for case in documented)
    assert any(case["case_time"] == "2018-02-03T08:00:00" and case["case_status"] == "failed" for case in documented)


def test_documented_case_includes_debug_context():
    report = _run_report_probe()

    case = next(c for c in report["documented_cases"] if c["case_time"] == "2024-01-11T08:00:00")

    assert case["matched"] is True
    assert case["signal_bar"]["time"] == "2024-01-11T08:00:00"
    assert "analysis" in case
    assert "recent_streak_legs" in case["analysis"]
    assert "price_qualified_legs" in case["analysis"]
    assert "selected_triplet_legs" in case["analysis"]
    assert "ranked_candidate_legs" not in case["analysis"]
    assert "eligible_ranking_legs" not in case["analysis"]
    assert "top3_strength_leg_times" not in case["analysis"]
    assert "latest_leg_in_top3" not in case["analysis"]
    assert "latest_leg_strength_rank" not in case["analysis"]


def test_2018_01_19_does_not_reuse_the_same_completed_wave_for_the_first_two_legs():
    report = _run_report_probe()

    signal = next((s for s in report["signals"] if s["signal_time"] == "2018-01-19T08:00:00"), None)

    if signal is None:
        return

    assert signal["legs"][0]["wave_start_time"] != signal["legs"][1]["wave_start_time"]


def test_2019_01_30_signal_is_filtered_when_middle_leg_does_not_own_the_new_price_low():
    report = _run_report_probe()

    signal = next((s for s in report["signals"] if s["signal_time"] == "2019-01-30T08:00:00"), None)

    assert signal is None


def test_2019_05_06_signal_is_filtered_when_selected_window_contains_more_than_five_raw_same_sign_waves():
    report = _run_report_probe()

    signal = next((s for s in report["signals"] if s["signal_time"] == "2019-05-06T08:00:00"), None)

    assert signal is None


def test_2019_11_25_signal_is_filtered_when_filtered_waves_are_not_contiguous():
    report = _run_report_probe()

    signal = next((s for s in report["signals"] if s["signal_time"] == "2019-11-25T08:00:00"), None)

    assert signal is None


def test_2023_06_13_signal_is_filtered_when_third_leg_does_not_beat_adjacent_green_separator_low():
    report = _run_report_probe()

    signal = next((s for s in report["signals"] if s["signal_time"] == "2023-06-13T08:00:00"), None)
    later_signal = next((s for s in report["signals"] if s["signal_time"] == "2023-06-15T08:00:00"), None)

    assert signal is None
    assert later_signal is not None


def test_2025_05_19_signal_is_filtered_when_latest_top_leg_is_below_trigger_strength_threshold():
    report = _run_report_probe()

    signal = next((s for s in report["signals"] if s["signal_time"] == "2025-05-19T08:00:00"), None)
    documented = next((s for s in report["signals"] if s["signal_time"] == "2025-05-23T08:00:00"), None)

    assert signal is None
    assert documented is not None


def test_2023_05_26_signal_is_filtered_when_middle_leg_does_not_make_new_price_low():
    report = _run_report_probe()

    signal = next((s for s in report["signals"] if s["signal_time"] == "2023-05-26T08:00:00"), None)

    assert signal is None
