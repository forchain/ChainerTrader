from datetime import datetime, timedelta

from binance_common.configuration import ConfigurationRestAPI
from binance_common.constants import SPOT_REST_API_PROD_URL
from binance_common.models import RateLimit
from binance_sdk_spot import Spot

from trader.common.logger import default
from trader.exchange.exchange_config import ExchangeConfig
from trader.exchange.exchange_type import ExchangeType
from trader.utils.kline import Kline
from trader.utils.symbol_interval import SymbolInterval

EXCHANGE_NAME = "BINANCE"

RECV_WINDOW = 5000

KLINE_LIMIT_MAX = 1000
KLINE_LIMIT_DEFAULT = 500

OLDEST_TIME = "2000-01-01 00:00:00"


class BinanceExchange:
    def __init__(self, cfg: ExchangeConfig, log=default()):
        self.log = log
        self.cfg = cfg
        self.log.info(f"Init Exchange {self.name()}")

        configuration_rest_api = ConfigurationRestAPI(
            api_key=cfg.api_key,
            api_secret=cfg.api_secret,
            base_path=SPOT_REST_API_PROD_URL,
            timeout=10000,
            backoff=1,
        )
        self.spot_client = Spot(config_rest_api=configuration_rest_api)

        self.account = None
        self.rate_limits: dict[str, datetime] = {}

    def name(self):
        return ExchangeType.BINANCE.name

    def start(self):
        if not self.ping():
            return False

        try:
            st = self.spot_client.rest_api.time().data().server_time
            self.server_time = st / 1000
            offset = self.server_time_offset()
            if offset >= RECV_WINDOW / 1000:
                raise Exception(f"server time offset:{offset}")

        except Exception as e:
            self.log.error(f"Start {self.name()} exchange: {e}")
            return False

        self.log.info(f"Start {self.name()} exchange: server_time={self.server_datetime()} server_time_offset={self.server_time_offset()}")

        return True

    def stop(self):
        self.log.info(f"Stop {self.name()} exchange")
        # if self.spot_ws_client:
        #    self.spot_ws_client.stop()

    def server_datetime(self):
        if self.server_time is None:
            return None

        dt = datetime.fromtimestamp(self.server_time)
        return dt

    def server_time_offset(self):
        return self.server_time - datetime.now().timestamp()

    def get_exchange_info(self, symbol):
        self.log.debug(f"get_exchange_info:{symbol}")
        exchange_info = self.spot_client.rest_api.exchange_info(symbol=symbol)
        return exchange_info

    def get_klines(
        self,
        si: SymbolInterval,
        start_time: int = None,
        end_time: int = None,
        limit: int = KLINE_LIMIT_DEFAULT,
    ) -> list[Kline]:
        r_limit = limit
        if r_limit > KLINE_LIMIT_MAX:
            r_limit = KLINE_LIMIT_MAX

        try:
            if start_time and end_time:
                start_time *= 1000
                end_time *= 1000
                rsp = self.spot_client.rest_api.klines(
                    si.symbol,
                    si.interval.value,
                    start_time=start_time,
                    end_time=end_time,
                    limit=r_limit,
                )
            else:
                rsp = self.spot_client.rest_api.klines(si.symbol, si.interval.value, limit=r_limit)
            ret = rsp.data()
        except Exception as e:
            self.log.error(f"{e}")
            return None

        kls = parse_klines(ret)

        if kls and len(kls) > 0:
            self.log.info(f"get klines: {len(kls)}/{len(ret)}  start={kls[0].open_datetime()} end={kls[len(kls)-1].close_datetime()}")
        else:
            self.log.info(f"get klines: 0/{len(ret)}")

        return kls

    def get_latest_klines(self, si: SymbolInterval, limit: int = KLINE_LIMIT_DEFAULT) -> list[Kline]:
        return self.get_klines(si, None, None, limit)

    def get_klines_by_start(
        self,
        si: SymbolInterval,
        start_time: int = None,
        limit: int = KLINE_LIMIT_DEFAULT,
    ) -> list[Kline]:
        r_end_time = int(datetime.now().timestamp())
        if start_time is None or start_time == 0:
            start_time = int(get_oldest_time().timestamp())
        return self.get_klines(si, start_time, r_end_time, limit)

    def get_account(self):
        self.log.debug("get account")
        self.account = self.spot_client.rest_api.get_account()
        return self.account

    def ping(self) -> bool:
        if self.has_rate_limit():
            self.log.error(f"Rate limit")
            return False

        try:
            response = self.spot_client.rest_api.ping()
            rate_limits = response.rate_limits
            if rate_limits:
                self.update_rate_limits(rate_limits)

        except Exception as e:
            self.log.error(e)
            return False

        return True

    def update_rate_limits(self, rate_limits: list[RateLimit]):
        for rl in rate_limits:
            if rl.retryAfter:
                self.rate_limits[rl.rateLimitType] = datetime.now() + timedelta(seconds=rl.retryAfter)
                self.log.info(f"Set rate limit:{rl.rateLimitType}={self.rate_limits[rl.rateLimitType]}")

    def has_rate_limit(self, typ: str = "REQUEST_WEIGHT") -> bool:
        if typ in self.rate_limits:
            if datetime.now() <= self.rate_limits[typ]:
                return True
        return False


def on_spot_ws_close(socket_manager):
    socket_manager.host.log.info(f"{socket_manager.host.name()} exchange spot websocket api client close")


def on_spot_ws_handler(socket_manager, message):
    socket_manager.host.log.info(f"{socket_manager.host.name()} handle message: {message}")


def get_oldest_time() -> datetime:
    return datetime.strptime(OLDEST_TIME, "%Y-%m-%d %H:%M:%S")


def parse_klines(data) -> list[Kline]:
    if data is None:
        return None

    R_LIST_LEN = 12
    ret: list[Kline] = []
    for d in data:
        if len(d) < R_LIST_LEN:
            raise Exception(f"kline length is error:{len(d)} != {R_LIST_LEN}")

        ret.append(
            Kline(
                int(d[0] / 1000),
                float(d[1]),
                float(d[2]),
                float(d[3]),
                float(d[4]),
                int(d[6] / 1000),
                float(d[5]),
                float(d[7]),
                int(d[8]),
                float(d[9]),
                float(d[10]),
                float(d[11]),
            )
        )
    return ret
