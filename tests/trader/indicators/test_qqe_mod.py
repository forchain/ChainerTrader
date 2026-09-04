"""
Test QQE MOD indicator with BTC-USDT 1h data.

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

# Move DB imports to inside function to avoid dependency issues in some envs
# from pymongo import MongoClient
# from trader.database.kline import KlineCol

from trader.exchange.binance.data import BinanceData
from trader.indicators.qqe_mod import QQEMod
from trader.utils.kline import Kline

load_dotenv()


SYMBOL_INTERVAL = "BTCUSDT-1h"
START_TIME = int(datetime.now().timestamp()) - 3600 * 24 * 30  # 30 days ago
END_TIME = int(datetime.now().timestamp())
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "output")
# DEBUG_TIMESTAMPS = [1763938800, 1764000000]  # Example debug timestamps
DEBUG_TIMESTAMPS = [1763938800, 1682938800]  # disable debug


class QQEModStrategy(bt.Strategy):
    """Strategy that uses QQE MOD indicator for testing and visualization."""

    params = dict(
        rsi_length_primary=6,
        rsi_smoothing_primary=5,
        qqe_factor_primary=3.0,
        threshold_primary=3.0,
        rsi_length_secondary=6,
        rsi_smoothing_secondary=5,
        qqe_factor_secondary=1.61,
        threshold_secondary=3.0,
        bollinger_length=50,
        bollinger_multiplier=0.35,
        debug_times=DEBUG_TIMESTAMPS,
    )

    def __init__(self):
        self.qqe_mod = QQEMod(
            self.data,
            rsi_length_primary=self.p.rsi_length_primary,
            rsi_smoothing_primary=self.p.rsi_smoothing_primary,
            qqe_factor_primary=self.p.qqe_factor_primary,
            threshold_primary=self.p.threshold_primary,
            rsi_length_secondary=self.p.rsi_length_secondary,
            rsi_smoothing_secondary=self.p.rsi_smoothing_secondary,
            qqe_factor_secondary=self.p.qqe_factor_secondary,
            threshold_secondary=self.p.threshold_secondary,
            bollinger_length=self.p.bollinger_length,
            bollinger_multiplier=self.p.bollinger_multiplier,
            debug_times=self.p.debug_times,
        )

    def next(self):
        pass


def get_klines_from_csv(path):
    """Load klines from CSV file (Binance format)."""
    if not os.path.exists(path):
        return None
        
    klines = []
    try:
        with open(path, 'r') as f:
            reader = csv.reader(f)
            header = next(reader, None) # Skip header
            if not header:
                return None
                
            for row in reader:
                try:
                    # Binance CSV format:
                    # open_time, open, high, low, close, volume, close_time, quote_volume, count, taker_buy_vol, taker_buy_quote_vol, ignore
                    k = Kline(
                        open_time=int(row[0]) // 1000,
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                        close_time=int(row[6]) // 1000,
                        vol_quote=float(row[7]),
                        trades=int(row[8]),
                        vol_taker_base=float(row[9]),
                        vol_taker_quote=float(row[10]),
                        ignore=float(row[11])
                    )
                    klines.append(k)
                except (ValueError, IndexError):
                    continue
    except Exception as e:
        print(f"Error reading CSV {path}: {e}")
        return None
        
    return klines


def get_klines():
    """Load klines from MongoDB or fallback to CSV."""
    # Try MongoDB first
    try:
        from pymongo import MongoClient
        from trader.database.kline import KlineCol

        db_uri = os.environ.get("TRADER_DB", "mongodb://localhost:27017/")
        db_name = os.environ.get("TRADER_DB_NAME", "trader")

        client = MongoClient(db_uri, serverSelectionTimeoutMS=2000)
        # Trigger connection check
        client.server_info()
        
        db = client[db_name]
        log = logging.getLogger(__name__)
        kline_col = KlineCol(db, log)

        klines = kline_col.get_klines(SYMBOL_INTERVAL, START_TIME, END_TIME)
        client.close()
        
        if klines and len(klines) > 0:
            return klines
    except Exception as e:
        print(f"MongoDB connection failed or no data (Import error or Connection error): {e}")
        print("Falling back to CSV data...")

    # Fallback to CSV
    # Look for data/BTCUSDT-1h-2023-05.csv relative to project root
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
    csv_path = os.path.join(project_root, "data", "BTCUSDT-1h-2023-05.csv")
    
    print(f"Loading from CSV: {csv_path}")
    return get_klines_from_csv(csv_path)


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


def extract_qqe_mod_series(indicator, length):
    """Extract QQE MOD line data for exporting."""
    return dict(
        secondary_qqe_trend_line=_line_to_list(indicator.l.secondary_qqe_trend_line, length),
        secondary_rsi_histogram=_line_to_list(indicator.l.secondary_rsi_histogram, length),
        qqe_up_signal=_line_to_list(indicator.l.qqe_up_signal, length),
        qqe_down_signal=_line_to_list(indicator.l.qqe_down_signal, length),
        bollinger_upper=_line_to_list(indicator.l.bollinger_upper, length),
        bollinger_lower=_line_to_list(indicator.l.bollinger_lower, length),
    )


def save_qqe_mod_csv(path, klines, series):
    """Save OHLC + QQE MOD lines to CSV."""
    total = len(klines)
    count = min(
        total,
        len(series["secondary_qqe_trend_line"]),
    )
    if count == 0:
        print("No QQE MOD data available to export.")
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
                "secondary_qqe_trend_line",
                "secondary_rsi_histogram",
                "qqe_up_signal",
                "qqe_down_signal",
                "bollinger_upper",
                "bollinger_lower",
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
                    series["secondary_qqe_trend_line"][-count + idx],
                    series["secondary_rsi_histogram"][-count + idx],
                    series["qqe_up_signal"][-count + idx],
                    series["qqe_down_signal"][-count + idx],
                    series["bollinger_upper"][-count + idx],
                    series["bollinger_lower"][-count + idx],
                ]
            )

    print(f"QQE MOD data exported to CSV: {path}")


def test_qqe_mod(main=False):
    """Test QQE MOD indicator with BTC-USDT 1h data."""
    klines = get_klines()

    if klines is None or len(klines) == 0:
        print(f"No klines found for {SYMBOL_INTERVAL}. Please download data first.")
        print(
            "Run: python -m trader --exchange '{\"ty\":\"BINANCE\"}' --db mongodb://localhost:27017/ "
            f"--tasks '[{{\"task_type\":\"UPDATE_KLINES\",\"symbol\":\"BTC-USDT\",\"interval\":\"1h\",\"start_time\":{START_TIME}}}]'"
        )
        return

    print(f"Loaded {len(klines)} klines")
    print(f"Date range: {klines[0].open_datetime()} - {klines[-1].open_datetime()}")

    cerebro = bt.Cerebro()

    if DEBUG_TIMESTAMPS:
        print(
            "启用 QQE MOD 调试时间 (UTC 秒): "
            + ", ".join(str(ts) for ts in DEBUG_TIMESTAMPS)
        )

    cerebro.addstrategy(
        QQEModStrategy,
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
        output_file = os.path.join(OUTPUT_DIR, "qqe_mod_btcusdt_2025.png")
        csv_file = os.path.join(OUTPUT_DIR, "qqe_mod_btcusdt_2025.csv")

        qqe_mod_series = extract_qqe_mod_series(
            strategy.qqe_mod, len(klines)
        )
        save_qqe_mod_csv(csv_file, klines, qqe_mod_series)

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
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    test_qqe_mod(True)
