from datetime import datetime, timedelta

from binance_common.configuration import ConfigurationRestAPI
from binance_common.constants import SPOT_REST_API_PROD_URL
from binance_common.models import RateLimit
from binance_sdk_spot import Spot
from binance_sdk_spot.rest_api.models import AccountCommissionResponse, NewOrderSideEnum, NewOrderTypeEnum

from trader.common.logger import default
from trader.exchange.balance import Balance
from trader.exchange.exchange_config import ExchangeConfig
from trader.exchange.exchange_type import ExchangeType
from trader.utils.kline import Kline
from trader.utils.operate import OperateType
from trader.utils.symbol_interval import SymbolInterval

EXCHANGE_NAME = "BINANCE"

RECV_WINDOW = 5

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
        self.commission: AccountCommissionResponse | None = None
        self.rate_limits: dict[str, datetime] = {}

    def name(self):
        return ExchangeType.BINANCE.name

    def start(self):
        if not self.ping():
            return False

        dt = self.time()
        self.log.info(f"Start {self.name()} exchange: server_time={dt} server_time_offset={self.server_time_offset()}")

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
                    si.symbol(),
                    si.interval.value,
                    start_time=start_time,
                    end_time=end_time,
                    limit=r_limit,
                )
            else:
                rsp = self.spot_client.rest_api.klines(si.symbol(), si.interval.value, limit=r_limit)
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
        if self.has_rate_limit():
            self.log.error("Rate limit")
            return self.account

        try:
            response = self.spot_client.rest_api.get_account(omit_zero_balances=True)
            rate_limits = response.rate_limits
            if rate_limits:
                self.update_rate_limits(rate_limits)

            self.account = response.data()
            self.log.info(f"set account:{self.account}")

        except Exception as e:
            self.log.error(e)

        return self.account

    def get_account_balance(self, asset: str) -> float:
        acct = self.get_account()
        if acct and acct.balances:
            for ba in acct.balances:
                if ba.asset == asset:
                    return float(ba.free)
        return 0

    def get_account_balances(self) -> list[Balance]:
        acct = self.get_account()

        ret: list[Balance] = []
        if acct and acct.balances:
            for ba in acct.balances:
                ret.append(Balance(asset=ba.asset, free=float(ba.free), locked=float(ba.locked)))

        return ret

    def account_commission(self, symbol: str = None) -> AccountCommissionResponse:
        if self.has_rate_limit():
            self.log.error("Rate limit")
            return self.commission

        try:
            response = self.spot_client.rest_api.account_commission(symbol=symbol)
            rate_limits = response.rate_limits
            if rate_limits:
                self.update_rate_limits(rate_limits)

            self.commission = response.data()
            self.log.info(f"set account commission:{self.commission}")

        except Exception as e:
            self.log.error(e)

        return self.commission

    def get_account_commission(self, symbol: str) -> float | None:
        commission = self.account_commission(symbol)
        if commission and commission.standard_commission and commission.standard_commission.taker:
            return float(commission.standard_commission.taker)
        return None

    def ping(self) -> bool:
        if self.has_rate_limit():
            self.log.error("Rate limit")
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

    def time(self) -> datetime:
        if self.has_rate_limit():
            self.log.error("Rate limit")
            return self.server_datetime()

        try:
            response = self.spot_client.rest_api.time()
            rate_limits = response.rate_limits
            if rate_limits:
                self.update_rate_limits(rate_limits)

            st = response.data().server_time
            self.server_time = st / 1000
            self.log.info(f"set server time:{self.server_datetime()}")

            offset = self.server_time_offset()
            if offset >= RECV_WINDOW:
                raise Exception(f"server time offset:{offset}")

        except Exception as e:
            self.log.error(e)

        return self.server_datetime()

    def exchange_info(self, symbol: str = None):
        if self.has_rate_limit():
            self.log.error("Rate limit")
            return None

        try:
            response = self.spot_client.rest_api.exchange_info(symbol=symbol)
            rate_limits = response.rate_limits
            if rate_limits:
                self.update_rate_limits(rate_limits)

            return response.data()

        except Exception as e:
            self.log.error(e)

        return None

    def new_order(self, symbol: str, op: OperateType, quantity: float = 0):
        if self.has_rate_limit("ORDERS"):
            self.log.error("Rate limit")
            return None

        try:
            response = self.spot_client.rest_api.new_order(
                symbol=symbol,
                side=NewOrderSideEnum[op.name].value,
                type=NewOrderTypeEnum["MARKET"].value,
                quantity=quantity,
            )

            rate_limits = response.rate_limits
            if rate_limits:
                self.update_rate_limits(rate_limits)

            data = response.data()
            self.log.info(f"new_order() response: {data}")

        except Exception as e:
            self.log.error(e)

    def delete_order(self, symbol: str):
        if self.has_rate_limit("ORDERS"):
            self.log.error("Rate limit")
            return None

        try:
            response = self.spot_client.rest_api.delete_order(
                symbol=symbol,
            )

            rate_limits = response.rate_limits
            if rate_limits:
                self.update_rate_limits(rate_limits)

            data = response.data()
            self.log.info(f"delete_order() response: {data}")

        except Exception as e:
            self.log.error(e)

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
