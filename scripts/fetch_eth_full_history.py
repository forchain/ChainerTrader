#!/usr/bin/env python3
"""
下载完整的 ETH-USDT 历史数据（4年），用于策略优化
"""
import requests
import pandas as pd
import time
from datetime import datetime, timedelta
import os

BINANCE_API = "https://api.binance.com/api/v3/klines"
SYMBOL = "ETHUSDT"
INTERVAL = "1h"
OUTPUT = "data/ETHUSDT-1h-20210101-20241231.csv"
LIMIT = 1000  # Binance API limit per request

def download_klines(symbol, interval, start_time, end_time):
    """Download klines from Binance with rate limiting"""
    all_klines = []
    current = start_time
    
    while current < end_time:
        params = {
            'symbol': symbol,
            'interval': interval,
            'startTime': int(current.timestamp() * 1000),
            'endTime': int((current + timedelta(hours=LIMIT-1)).timestamp() * 1000),
            'limit': LIMIT
        }
        
        try:
            resp = requests.get(BINANCE_API, params=params, timeout=10)
            resp.raise_for_status()
            klines = resp.json()
            
            if not klines:
                break
            
            all_klines.extend(klines)
            current = datetime.fromtimestamp(klines[-1][0] / 1000) + timedelta(hours=1)
            
            print(f"  Downloaded: {datetime.fromtimestamp(klines[0][0]/1000)} ~ "
                  f"{datetime.fromtimestamp(klines[-1][0]/1000)} ({len(klines)} candles)")
            
            time.sleep(0.3)  # Rate limiting
            
        except Exception as e:
            print(f"  Error: {e}, retrying...")
            time.sleep(1)
    
    return all_klines

print(f"Downloading {SYMBOL} {INTERVAL} from 2021-01-01 to 2024-12-31...")
start = datetime(2021, 1, 1)
end = datetime(2025, 1, 1)

klines = download_klines(SYMBOL, INTERVAL, start, end)

if klines:
    # Convert to DataFrame
    df = pd.DataFrame(klines, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume', 'ignore'
    ])
    
    # Convert timestamps to datetime
    df['datetime'] = pd.to_datetime(df['open_time'].astype(int), unit='ms')
    
    # Select and reorder columns
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 
             'close_time', 'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume', 'ignore']]
    
    # Convert numeric columns
    for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Save
    os.makedirs('data', exist_ok=True)
    df.to_csv(OUTPUT, index=False)
    
    print(f"\nDownload complete!")
    print(f"  Total candles: {len(df)}")
    print(f"  Time range: {df['datetime'].min()} to {df['datetime'].max()}")
    print(f"  File: {OUTPUT}")
    print(f"  Size: {os.path.getsize(OUTPUT) / 1024 / 1024:.1f} MB")
else:
    print("No data downloaded")
