#!/usr/bin/env python3
"""
通用的历史数据下载脚本 - 支持任意币对和时间框架

使用示例:
  uv run --with requests --with pandas python3 scripts/download_backtest_data.py --symbol ETH-USDT --interval 1h --years 4
  uv run --with requests --with pandas python3 scripts/download_backtest_data.py --symbol BTC-USDT --interval 1d --years 5
"""
import requests
import pandas as pd
import time
from datetime import datetime, timedelta
import os
import argparse

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

def main():
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
    
    klines = download_klines(args.symbol, args.interval, start_time, end_time)
    
    if klines:
        # Convert to DataFrame
        df = pd.DataFrame(klines, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume', 'ignore'
        ])
        
        # Convert timestamps to milliseconds (Binance CSV format)
        df['datetime'] = df['open_time'].astype(int)
        
        # Convert numeric columns
        for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Select columns in correct order
        df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 
                 'close_time', 'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume', 'ignore']]
        
        # Save
        os.makedirs('data', exist_ok=True)
        df.to_csv(output_file, index=False)
        
        # Statistics
        df_display = df.copy()
        df_display['datetime'] = pd.to_datetime(df_display['datetime'], unit='ms')
        
        print(f"\n✓ Download complete!")
        print(f"  Total candles: {len(df)}")
        print(f"  Time range: {df_display['datetime'].min()} to {df_display['datetime'].max()}")
        print(f"  File size: {os.path.getsize(output_file) / 1024 / 1024:.1f} MB")
        print(f"  Location: {output_file}")
        
        # Data quality check
        print(f"\n📊 Data quality:")
        print(f"  Missing values: {df[['open', 'high', 'low', 'close']].isna().sum().sum()}")
        print(f"  Date gaps: Check manually if needed")
        
    else:
        print("✗ No data downloaded")

if __name__ == '__main__':
    main()
