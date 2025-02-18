
import requests
import json

from trader.common import path
from trader.common.path import get_file_path


def get_symbol_top(api_key:str,limit=100):
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"

    params = {
        "start": 1,
        "limit": limit,
        "convert": "USD"
    }

    headers = {
        "Accepts": "application/json",
        "X-CMC_PRO_API_KEY": api_key
    }

    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        return None

    data = response.json()

    ret=[]
    for coin in data["data"]:
        ret.append(coin['symbol'])
    return ret

def write_symbols_top100_config(api_key:str,file_path="symbols_top100.txt",quote="USDT"):
    symbols=get_symbol_top(api_key)
    if symbols is None or len(symbols) <= 0:
        return False
    with open(get_file_path(file_path), "w", encoding="utf-8") as f:
        for sy in symbols:
            if sy == quote:
                continue
            f.write(sy + quote + "\n")
        return True

