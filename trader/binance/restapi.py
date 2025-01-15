
def get_restapi(stability=True):
    if stability:
        return get_restapi_by_index(0)

    # 上述列表的最后4个接口 (api1-api4) 会提供更好的性能，但其稳定性略为逊色。因此，请务必使用最适合的URL。
    return get_restapi_by_index(2)

def get_restapi_by_index(index):
    apis = ["https://api.binance.com",
            "https://api-gcp.binance.com",
            "https://api1.binance.com",
            "https://api2.binance.com",
            "https://api3.binance.com",
            "https://api4.binance.com"]
    if index >= len(apis):
        index = len(apis)-1
    return apis[index]

def getMarketRestAPI():
    # 对于仅发送公开市场数据的 API
    return "https://data-api.binance.vision"

def getTestnetRestAPI():
    return "https://testnet.binance.vision"