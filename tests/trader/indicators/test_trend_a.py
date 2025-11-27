"""
Test TrendA indicator with BTC-USDT 1h data.

Data preparation (run before test):
    python -m trader --exchange '{"ty":"BINANCE","api_key":"","api_secret":""}' \
      --db mongodb://localhost:27017/ \
      --tasks '[{"task_type":"UPDATE_KLINES","symbol":"BTC-USDT","interval":"1h","start_time":"2025-01-01 00:00:00"}]'
"""

import csv
import logging
import math
import os
from datetime import datetime

import backtrader as bt
import matplotlib.pyplot as plt
import pandas as pd
import pytest
from dotenv import load_dotenv
from matplotlib.ticker import ScalarFormatter

from trader.indicators.trend_a import TrendA
from trader.utils.ma import MAType

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


SYMBOL_INTERVAL = "BTCUSDT-1h"
START_TIME = int(datetime.now().timestamp()) - 3600 * 24 * 30  # 1 week ago
END_TIME = int(datetime.now().timestamp())
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "output")
# DEBUG_TIMESTAMPS = [1763938800, 1764000000]  # 2025-11-23 23:00 & 2025-11-24 16:00 UTC
DEBUG_TIMESTAMPS = [1763938800]  # disable debug


def _build_sample_dataframe():
    """Create deterministic OHLC data for unit tests."""
    periods = 240
    index = pd.date_range(start="2024-01-01", periods=periods, freq="h")
    base = pd.Series(range(periods), dtype=float)
    close = 20000.0 + base * 5.0
    open_ = close.shift(1).fillna(close.iloc[0])
    high = pd.concat([open_, close], axis=1).max(axis=1) + 15.0
    low = pd.concat([open_, close], axis=1).min(axis=1) - 15.0
    volume = 1000.0 + base * 2.0
    df = pd.DataFrame(
        dict(
            datetime=index,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
    )
    return df


@pytest.mark.parametrize("ma_type", [MAType.EMA, MAType.SMA, MAType.WMA])
def test_trend_a_outputs_for_supported_ma_types(ma_type):
    """Ensure all supported MA types generate stable values."""
    df = _build_sample_dataframe()
    cerebro = bt.Cerebro()

    class CaptureStrategy(bt.Strategy):
        params = dict(ma_type=ma_type)

        def __init__(self):
            self.trend_a = TrendA(
                self.data,
                ma_type=self.p.ma_type,
                ma_period=5,
                ma_period_smoothing=5,
            )

    cerebro.addstrategy(CaptureStrategy, ma_type=ma_type)
    data_feed = bt.feeds.PandasData(dataname=df, datetime="datetime")
    cerebro.adddata(data_feed)
    strategies = cerebro.run()
    strategy = strategies[0]
    line_length = len(df)
    open_values = _line_to_list(strategy.trend_a.l.open_line, line_length)
    trend_values = _line_to_list(strategy.trend_a.l.trend, line_length)
    open_valid = [value for value in open_values if not math.isnan(value)]
    trend_valid = [value for value in trend_values if not math.isnan(value)]
    assert len(open_valid) >= line_length - 10
    assert len(trend_valid) >= line_length - 10


def test_trend_a_rejects_unsupported_ma_type():
    """Unsupported MA selections should raise a ValueError."""
    df = _build_sample_dataframe()
    cerebro = bt.Cerebro()

    class InvalidStrategy(bt.Strategy):
        def __init__(self):
            TrendA(
                self.data,
                ma_type=MAType.VWMA,
                ma_period=5,
                ma_period_smoothing=5,
            )

    cerebro.addstrategy(InvalidStrategy)
    data_feed = bt.feeds.PandasData(dataname=df, datetime="datetime")
    cerebro.adddata(data_feed)
    with pytest.raises(ValueError):
        cerebro.run()


class TrendAStrategy(bt.Strategy):
    """Strategy that uses TrendA indicator for testing and visualization."""

    params = dict(
        ma_type=MAType.EMA,
        ma_period=77,
        ma_period_smoothing=21,
        debug_times=DEBUG_TIMESTAMPS,
    )

    def __init__(self):
        self.trend_a = TrendA(
            self.data,
            ma_type=self.p.ma_type,
            ma_period=self.p.ma_period,
            ma_period_smoothing=self.p.ma_period_smoothing,
            debug_times=self.p.debug_times,
        )

    def next(self):
        pass


def get_klines_from_db():
    """Load klines from MongoDB."""
    from pymongo import MongoClient  # noqa: E402

    from trader.database.kline import KlineCol  # noqa: E402

    db_uri = os.environ.get("TRADER_DB", "mongodb://localhost:27017/")
    db_name = os.environ.get("TRADER_DB_NAME", "trader")

    client = MongoClient(db_uri)
    db = client[db_name]

    log = logging.getLogger(__name__)
    kline_col = KlineCol(db, log)

    klines = kline_col.get_klines(SYMBOL_INTERVAL, START_TIME, END_TIME)
    client.close()

    return klines


def _line_to_list(line, length):
    """Convert backtrader line buffer to list of floats."""
    values = list(line.get(size=length))
    result = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = math.nan
        result.append(number)
    return result


def extract_trend_a_series(trend_indicator, length):
    """Extract TrendA line data for exporting."""
    return dict(
        open=_line_to_list(trend_indicator.l.open_line, length),
        close=_line_to_list(trend_indicator.l.close_line, length),
        high=_line_to_list(trend_indicator.l.high_line, length),
        low=_line_to_list(trend_indicator.l.low_line, length),
        highest_body=_line_to_list(trend_indicator.l.highest_body_line, length),
        lowest_body=_line_to_list(trend_indicator.l.lowest_body_line, length),
        trend=_line_to_list(trend_indicator.l.trend, length),
    )


def save_trend_a_csv(path, klines, series):
    """Save OHLC + TrendA lines to CSV."""
    total = len(klines)
    count = min(
        total,
        len(series["open"]),
    )
    if count == 0:
        print("No TrendA data available to export.")
        return

    klines_tail = klines[-count:]

    with open(path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(
            [
                "datetime",
                "open",
                "high",
                "low",
                "close",
                "trend_open",
                "trend_close",
                "trend_high",
                "trend_low",
                "trend_highest_body",
                "trend_lowest_body",
                "trend_value",
            ]
        )

        for idx, kline in enumerate(klines_tail):
            # Convert timestamp to UTC datetime
            utc_dt = datetime.utcfromtimestamp(kline.open_time)
            writer.writerow(
                [
                    utc_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    kline.open,
                    kline.high,
                    kline.low,
                    kline.close,
                    series["open"][-count + idx],
                    series["close"][-count + idx],
                    series["high"][-count + idx],
                    series["low"][-count + idx],
                    series["highest_body"][-count + idx],
                    series["lowest_body"][-count + idx],
                    series["trend"][-count + idx],
                ]
            )

    print(f"TrendA data exported to CSV: {path}")


def run_trend_a_manual(main=False):
    """Test TrendA indicator with BTC-USDT 1h data."""
    from trader.exchange.binance.data import BinanceData  # noqa: E402

    klines = get_klines_from_db()

    if klines is None or len(klines) == 0:
        print(f"No klines found for {SYMBOL_INTERVAL}. Please download data first.")
        print(
            "Run: python -m trader --exchange '{\"ty\":\"BINANCE\"}' --db mongodb://localhost:27017/ "
            f"--tasks '[{{\"task_type\":\"UPDATE_KLINES\",\"symbol\":\"BTC-USDT\",\"interval\":\"1h\",\"start_time\":{START_TIME}}}]'"
        )
        return

    print(f"Loaded {len(klines)} klines from {SYMBOL_INTERVAL}")
    print(f"Date range: {klines[0].open_datetime()} - {klines[-1].open_datetime()}")

    cerebro = bt.Cerebro()

    if DEBUG_TIMESTAMPS:
        print(
            "启用 TrendA 调试时间 (UTC 秒): "
            + ", ".join(str(ts) for ts in DEBUG_TIMESTAMPS)
        )

    cerebro.addstrategy(
        TrendAStrategy,
        ma_type=MAType.EMA,
        ma_period=77,
        ma_period_smoothing=21,
        debug_times=DEBUG_TIMESTAMPS,
    )

    data = BinanceData(klines)
    cerebro.adddata(data, name="BTCUSDT")

    cerebro.broker.setcash(100000.0)

    print(f"\nStarting Portfolio Value: {cerebro.broker.getvalue():.2f}")

    results = cerebro.run()
    strategy = results[0]

    print(f"Final Portfolio Value: {cerebro.broker.getvalue():.2f}")

    if main:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        output_file = os.path.join(OUTPUT_DIR, "trend_a_btcusdt_2025.png")
        csv_file = os.path.join(OUTPUT_DIR, "trend_a_btcusdt_2025.csv")

        trend_series = extract_trend_a_series(strategy.trend_a, len(klines))
        save_trend_a_csv(csv_file, klines, trend_series)

        # Use backtrader's interactive plot
        # Show interactive window first, then save after closing
        figs = cerebro.plot(
            style="candle",
            barup="green",
            bardown="red",
            volume=False,
            figsize=(24, 12),
            returnfig=True,
        )

        if figs and len(figs) > 0 and len(figs[0]) > 0:
            fig = figs[0][0]

            # Format Y-axis to show full numbers instead of scientific notation
            for ax in fig.axes:
                formatter = ScalarFormatter(useOffset=False)
                formatter.set_scientific(False)
                ax.yaxis.set_major_formatter(formatter)

            # Show interactive plot first
            plt.show()

            # After closing the window, save to file
            fig.savefig(output_file, dpi=150, bbox_inches="tight")
            print(f"\nChart saved to: {output_file}")
if __name__ == "__main__":
    run_trend_a_manual(True)
