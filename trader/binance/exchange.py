from binance.spot import Spot as Client

from trader.binance.restapi import get_restapi

EXCHANGE_NAME = "BINANCE"

class BinanceExchange:
    def __init__(self,log):
        self.log=log
        self.log.info(f"Init Exchange {self.name()}")

        base_url=get_restapi()
        self.spot_client=Client(base_url=base_url)

    def name(self):
        return EXCHANGE_NAME

    def start(self):
        try:
            self.spot_client.ping()
        except Exception as e:
            self.log.error(f"Start {self.name()} exchange: {e}")
        else:
            self.log.error(f"Start {self.name()} exchange")

    def stop(self):
        self.log.info(f"Stop {self.name()} exchange")