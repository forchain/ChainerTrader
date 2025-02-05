
import requests
import json

def get_symbol_top100(api_key:str):
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"

    params = {
        "start": 1,
        "limit": 100,
        "convert": "USD"
    }

    headers = {
        "Accepts": "application/json",
        "X-CMC_PRO_API_KEY": api_key
    }

    response = requests.get(url, headers=headers, params=params)
    data = response.json()

    ret=[]
    for coin in data["data"]:
        ret.append(f"{coin['name']} ({coin['symbol']}): ${coin['quote']['USD']['price']:.2f}")

    return ret