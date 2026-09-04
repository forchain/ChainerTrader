import os
import time
import json
import base64
import logging

from binance.spot import Spot as Client
from binance.lib.utils import config_logging
from binance.spot import Spot
from dotenv import load_dotenv
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from matplotlib.patheffects import Normal
from websocket import create_connection

from trader.binance.restapi import getMarketRestAPI, getTestnetRestAPI


def loadAPIConfig():
    # load .env file
    load_dotenv()

    # get env value
    apiKey = os.getenv("binanceAPIKey")
    apiSecret = os.getenv("binanceSecretKey")
    privateKey = os.getenv("binancePrivateKey")

    if apiKey:
        print("apiKey:", apiKey)
    if apiSecret:
        print("apiSecret:", apiSecret)
    if privateKey:
        print("privateKey:", privateKey)
    return apiKey,apiSecret,privateKey

def test_ping():
    config_logging(logging, logging.DEBUG)

    spot_client = Client(base_url=getTestnetRestAPI())
    logging.info(spot_client.ping())

def test_binanceSpot():
    client = Spot()

    # Get server timestamp
    print(client.time())
    # Get klines of BTCUSDT at 1m interval
    print(client.klines("BTCUSDT", "1m"))
    # Get last 10 klines of BNBUSDT at 1h interval
    print(client.klines("BNBUSDT", "1h", limit=10))

    # API key/secret are required for user data endpoints
    apiKey, _, privateKey = loadAPIConfig()
    assert apiKey is not None
    client = Spot(api_key=apiKey, private_key=privateKey)

    # Get account and balance information
    print(client.account())

    # Post a new order
    # params = {
    #     'symbol': 'BTCUSDT',
    #     'side': 'SELL',
    #     'type': 'LIMIT',
    #     'timeInForce': 'GTC',
    #     'quantity': 0.002,
    #     'price': 9500
    # }
    #
    # response = client.new_order(**params)
    # print(response)


def test_PayloadByEd25519Key():
    API_KEY, _, _= loadAPIConfig()
    # 设置身份验证：
    PRIVATE_KEY_PATH = ''
    assert PRIVATE_KEY_PATH is not None
    # 加载 private key。
    # 在这个例子中，private key 没有加密，但我们建议使用强密码以提高安全性。
    with open(PRIVATE_KEY_PATH, 'rb') as f:
        private_key = load_pem_private_key(data=f.read(), password=None)
    # 设置请求参数：
    params = {
        'apiKey': API_KEY,
        'symbol': 'BTCUSDT',
        'side': 'SELL',
        'type': 'LIMIT',
        'timeInForce': 'GTC',
        'quantity': '1.0000000',
        'price': '0.20'
    }
    # 参数中加时间戳：
    import time
    timestamp = int(time.time() * 1000)  # 以毫秒为单位的 UNIX 时间戳
    params['timestamp'] = timestamp
    # 参数中加签名：
    payload = '&'.join([f'{param}={value}' for param, value in sorted(params.items())])
    signature = base64.b64encode(private_key.sign(payload.encode('ASCII')))
    params['signature'] = signature.decode('ASCII')
    # 发送请求：
    request = {
        'id': 'my_new_order',
        'method': 'order.place',
        'params': params
    }
    ws = create_connection('wss://ws-api.binance.com:443/ws-api/v3')
    ws.send(json.dumps(request))
    result = ws.recv()
    ws.close()
    print(result)