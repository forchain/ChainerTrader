#!/usr/bin/env python3
"""
通用的历史数据下载脚本 - 支持任意币对和时间框架

DB 优先模式（推荐）:
  # 需要先安装项目：make install
  # 自动读取 .env 中的 TRADER_DB，优先从数据库读取，只下载缺失部分
  python3 scripts/download_backtest_data.py --symbol ETH-USDT --interval 1h --years 4
  python3 scripts/download_backtest_data.py --symbol BTC-USDT --interval 1d --years 5

纯 API 模式（无需安装，但每次全量下载）:
  uv run --with requests --with pandas python3 scripts/download_backtest_data.py --symbol ETH-USDT --interval 1h --years 4
  uv run --with requests --with pandas python3 scripts/download_backtest_data.py --symbol BTC-USDT --interval 1d --years 5

注意：若 .env 中未配置 TRADER_DB，自动回退到纯 API 模式。
"""
import asyncio
import os
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

BINANCE_API = "https://api.binance.com/api/v3/klines"
LIMIT = 1000  # Binance API limit per request

INTERVAL_HOURS = {
    "1m": 1/60, "3m": 3/60, "5m": 5/60, "15m": 15/60, "30m": 30/60,
    "1h": 1, "2h": 2, "4h": 4, "6h": 6, "8h": 8, "12h": 12,
    "1d": 24, "3d": 72, "1w": 168, "1M": 720  # Approximate for month
}


def download_klines(symbol, interval, start_time, end_time, max_retries=3):
    """Download klines from Binance with rate limiting and retry logic"""
    all_klines = []
    current = start_time
    batch_size_hours = INTERVAL_HOURS.get(interval, 1) * (LIMIT - 1)

    total_batches = int((end_time - start_time).total_seconds() / (batch_size_hours * 3600)) + 1
    current_batch = 0

    while current < end_time:
        current_batch += 1
        batch_end = min(current + timedelta(hours=batch_size_hours), end_time)

        for retry in range(max_retries):
            try:
                params = {
                    'symbol': symbol.replace('-', ''),
                    'interval': interval,
                    'startTime': int(current.timestamp() * 1000),
                    'endTime': int(batch_end.timestamp() * 1000),
                    'limit': LIMIT
                }

                resp = requests.get(BINANCE_API, params=params, timeout=15)
                resp.raise_for_status()
                klines = resp.json()

                if not klines:
                    print(f"  [Batch {current_batch}/{total_batches}] No data, moving to next period")
                    break

                all_klines.extend(klines)
                batch_time_range = f"{datetime.fromtimestamp(klines[0][0]/1000).strftime('%Y-%m-%d %H:%M')} ~ " \
                                 f"{datetime.fromtimestamp(klines[-1][0]/1000).strftime('%Y-%m-%d %H:%M')}"
                print(f"  [Batch {current_batch}/{total_batches}] {batch_time_range} ({len(klines)} candles)")
                break

            except requests.exceptions.Timeout:
                if retry < max_retries - 1:
                    print(f"  [Batch {current_batch}] Timeout (retry {retry+1}/{max_retries})")
                    time.sleep(2 ** retry)
                else:
                    print(f"  [Batch {current_batch}] Failed after {max_retries} retries")
            except Exception as e:
                if retry < max_retries - 1:
                    print(f"  [Batch {current_batch}] Error: {e} (retry {retry+1}/{max_retries})")
                    time.sleep(2 ** retry)
                else:
                    print(f"  [Batch {current_batch}] Failed: {e}")

        current = batch_end + timedelta(hours=INTERVAL_HOURS.get(interval, 1))
        time.sleep(0.3)  # Rate limiting

    return all_klines


def save_klines_to_csv(klines, output_file):
    """Convert raw Binance API klines list to CSV and save."""
    df = pd.DataFrame(klines, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume', 'ignore'
    ])

    df['datetime'] = df['open_time'].astype(int)

    for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume',
             'close_time', 'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume', 'ignore']]

    os.makedirs('data', exist_ok=True)
    df.to_csv(output_file, index=False)
    return df


def print_stats(df, output_file):
    """Print download/export statistics."""
    df_display = df.copy()
    df_display['datetime'] = pd.to_datetime(df_display['datetime'], unit='ms')

    print(f"\n✓ Complete!")
    print(f"  Total candles: {len(df)}")
    print(f"  Time range: {df_display['datetime'].min()} to {df_display['datetime'].max()}")
    print(f"  File size: {os.path.getsize(output_file) / 1024 / 1024:.1f} MB")
    print(f"  Location: {output_file}")

    print(f"\n  Data quality:")
    print(f"  Missing values: {df[['open', 'high', 'low', 'close']].isna().sum().sum()}")


def try_db_download(symbol, interval, start_time, end_time, output_file):
    """
    DB 优先下载：检查数据库已有数据，只补充下载缺失部分，最后从 DB 导出 CSV。

    返回 True 表示成功，False 表示 DB 不可用（应回退到 API 模式）。
    """
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        return False

    db_uri = os.environ.get("TRADER_DB")
    if not db_uri:
        return False

    try:
        from trader.common.config import Config
        from trader.common.logger import Logger
        from trader.database.manager import DatabaseManager
        from trader.exchange.binance.exchange import BinanceExchange
        from trader.exchange.exchange_config import parse_exchange_config
        from trader.task.update_klines_task import download_range
        from trader.utils.symbol_interval import Interval, Symbol, SymbolInterval, add_time_duration

        db_name = os.environ.get("TRADER_DB_NAME", "trader")

        # Minimal logger/config for framework usage
        cfg = Config(log_level="INFO", db=db_uri, db_name=db_name)
        log = Logger(cfg)
        db = DatabaseManager(cfg, log)
        db.start()

        # Build SymbolInterval: "ETH-USDT" + "1h" → "ETHUSDT-1h"
        interval_map = {v: f"INTERVAL_{v}" for v in INTERVAL_HOURS}
        interval_enum = Interval[f"INTERVAL_{interval}"]
        si = SymbolInterval(symbol, interval_enum)
        col_name = si.name()

        print(f"  [DB] Checking collection: klines-{col_name}")

        start_ts = int(start_time.timestamp())
        end_ts = int(end_time.timestamp())

        db_first = db.kline.get_first_kline(col_name)
        db_last = db.kline.get_latest_kline(col_name)

        need_download = []  # list of (range_start, range_end) to download

        if db_first is None or db_last is None:
            print(f"  [DB] No existing data, will download full range")
            need_download.append((start_ts, end_ts))
        else:
            db_first_time = db_first.open_time
            db_last_time = db_last.open_time
            print(f"  [DB] Existing data: {datetime.fromtimestamp(db_first_time)} ~ {datetime.fromtimestamp(db_last_time)}")

            # Case 1: end < db_first → download [start, end]
            if end_ts < db_first_time:
                print(f"  [DB] Case: requested range is entirely before DB data")
                need_download.append((start_ts, end_ts))

            # Case 2: start < db_first <= end <= db_last → fill before
            elif start_ts < db_first_time <= end_ts <= db_last_time:
                range_end = add_time_duration(db_first_time, interval_enum, -1)
                print(f"  [DB] Case: missing prefix, downloading [{datetime.fromtimestamp(start_ts)}, {datetime.fromtimestamp(range_end)})")
                need_download.append((start_ts, range_end))

            # Case 3: db_first <= start <= end <= db_last → fully covered
            elif db_first_time <= start_ts and end_ts <= db_last_time:
                print(f"  [DB] Case: fully covered by DB, skipping API download")

            # Case 4: start >= db_first and db_last < end → fill after
            elif start_ts >= db_first_time and db_last_time < end_ts:
                range_start = add_time_duration(db_last_time, interval_enum, 1)
                print(f"  [DB] Case: missing suffix, downloading ({datetime.fromtimestamp(range_start)}, {datetime.fromtimestamp(end_ts)}]")
                need_download.append((range_start, end_ts))

            # Case 5: start < db_first and db_last < end → fill both sides
            elif start_ts < db_first_time and db_last_time < end_ts:
                range_end = add_time_duration(db_first_time, interval_enum, -1)
                range_start = add_time_duration(db_last_time, interval_enum, 1)
                print(f"  [DB] Case: missing both prefix and suffix, downloading 2 segments")
                need_download.append((start_ts, range_end))
                need_download.append((range_start, end_ts))

        # Download missing ranges if needed
        if need_download:
            exchange_cfg_json = os.environ.get("TRADER_EXCHANGE", "BINANCE")
            ex_cfg = parse_exchange_config(exchange_cfg_json)
            exchange = BinanceExchange(ex_cfg, log.log())

            quit_event = asyncio.Event()

            async def download_all():
                for range_start, range_end in need_download:
                    ok = await download_range(
                        "download_backtest_data",
                        log,
                        db,
                        col_name,
                        exchange,
                        si,
                        range_start,
                        range_end,
                        quit_event,
                    )
                    if not ok:
                        raise RuntimeError(f"download_range failed for [{datetime.fromtimestamp(range_start)}, {datetime.fromtimestamp(range_end)}]")

            asyncio.run(download_all())

        # Export from DB to CSV
        print(f"  [DB] Exporting from database to CSV...")
        klines = db.kline.get_klines(col_name, start_ts, end_ts)

        if not klines:
            raise RuntimeError("No klines found in DB after download")

        rows = []
        for kl in klines:
            rows.append({
                'datetime': kl.open_time * 1000,   # seconds → milliseconds
                'open': kl.open,
                'high': kl.high,
                'low': kl.low,
                'close': kl.close,
                'volume': kl.volume,
                'close_time': kl.close_time * 1000,
                'quote_volume': kl.vol_quote,
                'count': int(kl.trades),
                'taker_buy_volume': kl.vol_taker_base,
                'taker_buy_quote_volume': kl.vol_taker_quote,
                'ignore': kl.ignore,
            })

        df = pd.DataFrame(rows, columns=[
            'datetime', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume', 'ignore'
        ])

        os.makedirs('data', exist_ok=True)
        df.to_csv(output_file, index=False)

        db.stop()
        return df

    except Exception as e:
        print(f"  [DB] Warning: DB mode failed ({e}), falling back to direct API download...")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Download historical Binance data for backtesting')
    parser.add_argument('--symbol', default='ETH-USDT', help='Trading pair (e.g., ETH-USDT, BTC-USDT)')
    parser.add_argument('--interval', default='1h', help='Interval (1m, 5m, 1h, 4h, 1d, 1w, 1M)')
    parser.add_argument('--years', type=int, default=4, help='Years of history to download (default: 4)')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD), overrides --years')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD), default: today')

    args = parser.parse_args()

    # Parse dates
    if args.end_date:
        end_time = datetime.strptime(args.end_date, '%Y-%m-%d')
    else:
        end_time = datetime.now()

    if args.start_date:
        start_time = datetime.strptime(args.start_date, '%Y-%m-%d')
    else:
        start_time = end_time - timedelta(days=365 * args.years)

    # Generate filename
    symbol_file = args.symbol.replace('-', '')
    start_str = start_time.strftime('%Y%m%d')
    end_str = end_time.strftime('%Y%m%d')
    output_file = f"data/{symbol_file}-{args.interval}-{start_str}-{end_str}.csv"

    print(f"Downloading {args.symbol} {args.interval} from {start_time.date()} to {end_time.date()}")
    print(f"Output: {output_file}\n")

    # Try DB-first mode
    result = try_db_download(args.symbol, args.interval, start_time, end_time, output_file)

    if result is not False:
        # DB mode succeeded
        print_stats(result, output_file)
        return

    # Fallback: direct API download
    klines = download_klines(args.symbol, args.interval, start_time, end_time)

    if klines:
        df = save_klines_to_csv(klines, output_file)
        print_stats(df, output_file)
    else:
        print("✗ No data downloaded")


if __name__ == '__main__':
    main()
