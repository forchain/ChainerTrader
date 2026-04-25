import json
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


def _load_documented_cases():
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "macd_triple_divergence_documented_cases.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def test_report_includes_signal_context_for_known_top_case():
    report = _run_report_probe()

    signal = next(s for s in report["signals"] if s["signal_time"] == "2025-05-23T08:00:00")

    assert signal["signal_type"] == "top_divergence"
    assert len(signal["legs"]) == 3
    assert signal["conditions"]["price_higher_highs"]["passed"] is True
    assert signal["conditions"]["macd_lower_highs"]["passed"] is True
    assert signal["legs"][0]["price_on_macd_peak_bar"] < signal["legs"][1]["price_on_macd_peak_bar"] < signal["legs"][2]["price_on_macd_peak_bar"]
    assert signal["legs"][0]["macd_peak"] > signal["legs"][1]["macd_peak"] > signal["legs"][2]["macd_peak"]
    assert "is_documented_case" not in signal
    assert "documented_case_status" not in signal


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


def test_report_covers_all_documented_fixture_cases_as_regular_signals():
    report = _run_report_probe()

    signal_times = {signal["signal_time"] for signal in report["signals"]}
    expected = {case["case_time"] for case in _load_documented_cases()}

    assert expected.issubset(signal_times)
    assert "documented_cases" not in report


def test_report_omits_filtered_false_positive_examples():
    report = _run_report_probe()

    signal = next((s for s in report["signals"] if s["signal_time"] == "2019-01-30T08:00:00"), None)
    later_signal = next((s for s in report["signals"] if s["signal_time"] == "2023-06-15T08:00:00"), None)

    assert signal is None
    assert later_signal is not None


def test_report_trade_records_include_entry_signal_time_for_confirmed_entries():
    report = _run_report_probe()

    trades_with_signal_time = [trade for trade in report["trades"] if trade.get("entry_signal_time")]

    assert trades_with_signal_time
    assert trades_with_signal_time[0]["entry_signal_time"].endswith("T08:00:00")
