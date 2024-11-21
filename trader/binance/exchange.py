from binance.spot import Spot as Client

from trader.binance.restapi import get_restapi

EXCHANGE_NAME = "BINANCE"

class BinanceExchange:
    def __init__(self,log):
        self.log=log
        self.log.info(f"Init Exchange {self.name()}")

        base_url=get_restapi(False)
        self.spot_client=Client(base_url=base_url)

    def name(self):
        return EXCHANGE_NAME

    def start(self):
        self.log.info(f"Start {self.name()} exchange")

        info = self.spot_client.exchange_info()
        self.log.info(f"Get {self.name()} exchange_info:{info}")

    def stop(self):
        self.log.info(f"Stop {self.name()} exchange")