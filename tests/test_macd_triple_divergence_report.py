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


def test_report_includes_near_zero_separator_details_and_replacement_trade_trace():
    report = _run_report_probe()

    near_zero_signal = next(s for s in report["signals"] if s["signal_time"] == "2024-05-03T08:00:00")
    near_zero_separators = [sep for sep in near_zero_signal["conditions"]["separator_details"] if sep["mode"] == "near_zero"]

    assert near_zero_signal["signal_type"] == "bottom_divergence"
    assert near_zero_separators
    assert near_zero_separators[0]["separator_ratio"] is not None
    assert near_zero_separators[0]["noise_cluster_ratio_threshold"] == DEFAULT_NOISE_CLUSTER_RATIO
    assert near_zero_separators[0]["from_time"] is not None
    assert near_zero_separators[0]["to_time"] is not None

    replacement_signal = next(s for s in report["signals"] if s["signal_time"] == "2025-05-23T08:00:00")
    replacement_trade_id = replacement_signal["trade_outcome"]["trade_id"]
    replaced_trade = next(t for t in report["trades"] if t.get("replacement_trade_id") == replacement_trade_id)

    assert replacement_signal["trade_outcome"]["status"] == "entered"
    assert replaced_trade["exit_reason_code"] == "signal_replaced"
    assert replaced_trade["exit_reason_label"] == "新交易信号强制平仓"
    assert f"replacement_trade_id={replacement_trade_id}" in replaced_trade["exit_reason_detail"]


def test_documented_2020_02_13_signal_enters_after_prior_trade_is_resolved():
    report = _run_report_probe()

    signal = next(s for s in report["signals"] if s["signal_time"] == "2020-02-13T08:00:00")
    trade = next(t for t in report["trades"] if t["id"] == signal["trade_outcome"]["trade_id"])

    assert signal["direction"] == "SHORT"
    assert signal["trade_outcome"]["status"] == "entered"
    assert trade["dir"] == "S"
    assert trade["entry_signal_time"] == "2020-02-13T08:00:00"
    assert trade["entry"] == "2020-02-14T08:00:00"


def test_documented_2020_02_10_replacement_enters_next_day_and_uses_strategy_stop():
    report = _run_report_probe()

    signal = next(s for s in report["signals"] if s["signal_time"] == "2020-02-10T08:00:00")
    trade = next(t for t in report["trades"] if t["id"] == signal["trade_outcome"]["trade_id"])

    assert signal["trade_outcome"]["status"] == "entered"
    assert trade["entry"] == "2020-02-11T08:00:00"
    assert trade["exit_signal_time"] == "2020-02-11T08:00:00"
    assert trade["exit_reason_code"] == "strategy_stop"
    assert trade["exit_reason_label"] == "策略止损逻辑退出"
    assert trade["exit_reason_detail"] == "MACD 三背离后续走势失效"


def test_documented_2018_02_03_follow_through_failure_is_classified_as_strategy_stop():
    report = _run_report_probe()

    trade = next(t for t in report["trades"] if t["entry_signal_time"] == "2018-02-03T08:00:00")

    assert trade["exit_signal_time"] == "2018-02-04T08:00:00"
    assert trade["exit_reason_code"] == "strategy_stop"
    assert trade["exit_reason_label"] == "策略止损逻辑退出"
    assert trade["exit_reason_detail"] == "MACD 三背离后续走势失效"


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
