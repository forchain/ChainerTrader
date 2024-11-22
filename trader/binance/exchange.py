from datetime import datetime
from time import sleep

from binance.spot import Spot as Client

from trader.binance.restapi import get_restapi

EXCHANGE_NAME = "BINANCE"

RECV_WINDOW = 5000

class BinanceExchange:
    def __init__(self,cfg,log):
        self.log=log
        self.cfg=cfg
        self.log.info(f"Init Exchange {self.name()}")

        base_url=get_restapi(False)
        self.spot_client=Client(base_url=base_url)

    def name(self):
        return EXCHANGE_NAME

    def start(self):
        try:
            self.spot_client.ping()
            self.server_time = self.spot_client.time()["serverTime"]
            self.server_time = self.server_time /1000
            offset = self.server_time_offset()
            if offset >= RECV_WINDOW/1000:
                raise Exception(f"server time offset:{offset}")

            self.update_exchange_info()
        except Exception as e:
            self.log.error(f"Start {self.name()} exchange: {e}")
            return False

        self.log.info(f"Start {self.name()} exchange: server_time={self.server_datetime()} server_time_offset={self.server_time_offset()}")
        return True

    def stop(self):
        self.log.info(f"Stop {self.name()} exchange")

    def server_datetime(self):
        if self.server_time is None:
            return None

        dt = datetime.fromtimestamp(self.server_time)
        return dt

    def server_time_offset(self):
        return self.server_time-datetime.now().timestamp()

    def update_exchange_info(self):
        if self.cfg.symbols:
            self.log.debug(f"update_exchange_info:{self.cfg.symbols}")
            self.exchange_info = self.spot_client.exchange_info(symbols=self.cfg.symbols_list())
        else:
            self.exchange_info = None
        return self.exchange_info
