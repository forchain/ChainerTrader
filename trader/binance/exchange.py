from datetime import datetime
from time import sleep

from binance.spot import Spot as Client
from binance.websocket.spot.websocket_api import SpotWebsocketAPIClient

from trader.binance.restapi import get_restapi
from trader.common.logger import default
from trader.task.task_config import get_symbols_from_cfg
from trader.utils.kline import Kline
from trader.utils.symbol_interval import SymbolInterval, add_time_duration

EXCHANGE_NAME = "BINANCE"

RECV_WINDOW = 5000

KLINE_LIMIT_MAX = 1000
KLINE_LIMIT_DEFAULT = 500

OLDEST_TIME  = "2000-01-01 00:00:00"

class BinanceExchange:
    def __init__(self,cfg,log=default()):
        self.log=log
        self.cfg=cfg
        self.log.info(f"Init Exchange {self.name()}")

        base_url=get_restapi(False)
        self.spot_client=Client(base_url=base_url)
        #self.spot_ws_client = SpotWebsocketAPIClient(on_message=on_spot_ws_handler, on_close=on_spot_ws_close)
        #self.spot_ws_client.socket_manager.host = self

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

        except Exception as e:
            self.log.error(f"Start {self.name()} exchange: {e}")
            return False

        self.log.info(f"Start {self.name()} exchange: server_time={self.server_datetime()} server_time_offset={self.server_time_offset()}")

        return True

    def stop(self):
        self.log.info(f"Stop {self.name()} exchange")
        #if self.spot_ws_client:
        #    self.spot_ws_client.stop()

    def server_datetime(self):
        if self.server_time is None:
            return None

        dt = datetime.fromtimestamp(self.server_time)
        return dt

    def server_time_offset(self):
        return self.server_time-datetime.now().timestamp()

    def get_exchange_info(self,symbol):
        self.log.debug(f"get_exchange_info:{symbol}")
        exchange_info = self.spot_client.exchange_info(symbol=symbol)
        return exchange_info

    def get_klines(self,si:SymbolInterval,start_time:int=None,end_time:int=None,limit:int=KLINE_LIMIT_DEFAULT)->[Kline]:
        r_limit=limit
        if r_limit > KLINE_LIMIT_MAX:
            r_limit=KLINE_LIMIT_MAX

        if start_time and end_time:
            start_time *= 1000
            end_time *= 1000
            ret = self.spot_client.klines(si.symbol,si.interval.value,startTime=start_time,endTime=end_time,limit=r_limit)
        else:
            ret = self.spot_client.klines(si.symbol, si.interval.value,limit=r_limit)
        kls = parse_klines(ret)

        if kls and len(kls) > 0:
            self.log.info(f"get klines: {len(kls)}/{len(ret)}  start={kls[0].open_datetime()} end={kls[len(kls)-1].close_datetime()}")
        else:
            self.log.info(f"get klines: 0/{len(ret)}")

        return kls

    def get_latest_klines(self,si:SymbolInterval,limit:int=KLINE_LIMIT_DEFAULT)->[Kline]:
        return self.get_klines(si,None,None,limit)

    def get_klines_by_start(self,si:SymbolInterval,start_time:int=None,limit:int=KLINE_LIMIT_DEFAULT)->[Kline]:
        r_end_time = int(datetime.now().timestamp())
        if start_time is None:
            start_time = int(get_oldest_time().timestamp())
        return self.get_klines(si,start_time,r_end_time,limit)


def on_spot_ws_close(socket_manager):
    socket_manager.host.log.info(f"{socket_manager.host.name()} exchange spot websocket api client close")

def on_spot_ws_handler(socket_manager,message):
    socket_manager.host.log.info(f"{socket_manager.host.name()} handle message: {message}")


def get_oldest_time()->datetime:
    return datetime.strptime(OLDEST_TIME, "%Y-%m-%d %H:%M:%S")

def parse_klines(data)->[Kline]:
    if data is None:
        return None

    R_LIST_LEN=12
    ret:[Kline]=[]
    for d in data:
        if len(d) < R_LIST_LEN:
            raise Exception(f"kline length is error:{len(d)} != {R_LIST_LEN}")

        ret.append(Kline(
            int(d[0]/1000),
            float(d[1]),
            float(d[2]),
            float(d[3]),
            float(d[4]),
            int(d[6]/1000),
            float(d[5]),
            float(d[7]),
            int(d[8]),
            float(d[9]),
            float(d[10]),
            float(d[11]),
        ))
    return ret