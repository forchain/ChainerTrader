from binance.spot import Spot
import os
from dotenv import load_dotenv


def test_binanceSpot():
    # load .env file
    load_dotenv()

    # get env value
    apiKey = os.getenv("binanceAPIKey")
    apiSecret = os.getenv("binanceSecretKey")

    if apiKey is None or apiSecret is None:
        print("No config .env for API key")
        return

    print("apiKey:", apiKey)
    print("apiSecret:", apiSecret)


    client = Spot()

    # Get server timestamp
    print(client.time())
    # Get klines of BTCUSDT at 1m interval
    print(client.klines("BTCUSDT", "1m"))
    # Get last 10 klines of BNBUSDT at 1h interval
    print(client.klines("BNBUSDT", "1h", limit=10))

    # API key/secret are required for user data endpoints
    client = Spot(api_key=apiKey, api_secret=apiSecret)

    # Get account and balance information
    print(client.account())

    # Post a new order
    params = {
        'symbol': 'BTCUSDT',
        'side': 'SELL',
        'type': 'LIMIT',
        'timeInForce': 'GTC',
        'quantity': 0.002,
        'price': 9500
    }

    response = client.new_order(**params)
    print(response)