"""
Test SuperTrend indicator with BTC-USDT 1h data.

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
from dotenv import load_dotenv
from matplotlib.ticker import ScalarFormatter
from pymongo import MongoClient

from trader.database.kline import KlineCol
from trader.exchange.binance.data import BinanceData
from trader.indicators.super_trend import SuperTrend

load_dotenv()


SYMBOL_INTERVAL = "BTCUSDT-1h"
START_TIME = int(datetime.now().timestamp()) - 3600 * 24 * 30  # 30 days ago
END_TIME = int(datetime.now().timestamp())
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "output")
# DEBUG_TIMESTAMPS = [1763938800, 1764000000]  # Example debug timestamps
DEBUG_TIMESTAMPS = []  # disable debug


class SuperTrendStrategy(bt.Strategy):
    """Strategy that uses SuperTrend indicator for testing and visualization."""

    params = dict(
        periods=10,
        multiplier=3.0,
        change_atr=True,
        debug_times=DEBUG_TIMESTAMPS,
    )

    def __init__(self):
        self.super_trend = SuperTrend(
            self.data,
            periods=self.p.periods,
            multiplier=self.p.multiplier,
            change_atr=self.p.change_atr,
            debug_times=self.p.debug_times,
        )

    def next(self):
        pass


def get_klines_from_db():
    """Load klines from MongoDB."""
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


def extract_super_trend_series(indicator, length):
    """Extract SuperTrend line data for exporting."""
    return dict(
        up=_line_to_list(indicator.l.up, length),
        dn=_line_to_list(indicator.l.dn, length),
        trend=_line_to_list(indicator.l.trend, length),
        buy_signal=_line_to_list(indicator.l.buy_signal, length),
        sell_signal=_line_to_list(indicator.l.sell_signal, length),
    )


def save_super_trend_csv(path, klines, series):
    """Save OHLC + SuperTrend lines to CSV."""
    total = len(klines)
    count = min(
        total,
        len(series["up"]),
    )
    if count == 0:
        print("No SuperTrend data available to export.")
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
                "super_trend_up",
                "super_trend_dn",
                "super_trend_trend",
                "buy_signal",
                "sell_signal",
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
                    series["up"][-count + idx],
                    series["dn"][-count + idx],
                    series["trend"][-count + idx],
                    series["buy_signal"][-count + idx],
                    series["sell_signal"][-count + idx],
                ]
            )

    print(f"SuperTrend data exported to CSV: {path}")


def test_super_trend(main=False):
    """Test SuperTrend indicator with BTC-USDT 1h data."""
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
            "启用 SuperTrend 调试时间 (UTC 秒): "
            + ", ".join(str(ts) for ts in DEBUG_TIMESTAMPS)
        )

    cerebro.addstrategy(
        SuperTrendStrategy,
        periods=10,
        multiplier=3.0,
        change_atr=True,
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
        output_file = os.path.join(OUTPUT_DIR, "super_trend_btcusdt_2025.png")
        csv_file = os.path.join(OUTPUT_DIR, "super_trend_btcusdt_2025.csv")

        super_trend_series = extract_super_trend_series(
            strategy.super_trend, len(klines)
        )
        save_super_trend_csv(csv_file, klines, super_trend_series)

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
    test_super_trend(True)


