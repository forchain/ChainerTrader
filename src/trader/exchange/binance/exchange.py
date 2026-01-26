from datetime import datetime, timedelta
from typing import Optional

from binance_common.configuration import ConfigurationRestAPI
from binance_common.constants import SPOT_REST_API_PROD_URL
from binance_common.models import RateLimit
from binance_sdk_spot import Spot
from binance_sdk_spot.rest_api.models import AccountCommissionResponse, NewOrderSideEnum, NewOrderTypeEnum
import requests
import time
import hmac
import hashlib
from urllib.parse import urlencode

from trader.common.logger import default
from trader.exchange.balance import Balance
from trader.exchange.exchange_config import ExchangeConfig, MarginMode
from trader.exchange.exchange_type import ExchangeType
from trader.utils.kline import Kline
from trader.utils.operate import OperateType
from trader.utils.symbol_interval import SymbolInterval, Symbol

EXCHANGE_NAME = "BINANCE"

RECV_WINDOW = 5

KLINE_LIMIT_MAX = 1000
KLINE_LIMIT_DEFAULT = 500

OLDEST_TIME = "2000-01-01 00:00:00"

# Binance Margin API base URL
MARGIN_API_BASE_URL = "https://api.binance.com/sapi/v1"


class BinanceExchange:
    def __init__(self, cfg: ExchangeConfig, log=default()):
        self.log = log
        self.cfg = cfg
        self.margin_mode = cfg.margin_mode if hasattr(cfg, 'margin_mode') else MarginMode.SPOT
        self.log.info(f"Init Exchange {self.name()} with margin_mode={self.margin_mode.value}")

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
        self.server_time: Optional[float] = None

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

    def new_order(self, symbol:Symbol, op: OperateType, quantity: float = 0):
        if self.has_rate_limit("ORDERS"):
            self.log.error("Rate limit")
            return None

        if self.margin_mode != MarginMode.SPOT:
            return self._new_margin_order(symbol, op, quantity)

        try:
            side_name = op.name
            if op == OperateType.SHORT:
                side_name = "SELL"
            elif op == OperateType.LONG:
                side_name = "BUY"
            elif op == OperateType.CLOSE:
                side_name = "SELL"
                self.log.warning("CLOSE operation in SPOT mode mapped to SELL")

            response = self.spot_client.rest_api.new_order(
                symbol=symbol.name(),
                side=NewOrderSideEnum[side_name].value,
                type=NewOrderTypeEnum["MARKET"].value,
                quantity=quantity,
            )

            rate_limits = response.rate_limits
            if rate_limits:
                self.update_rate_limits(rate_limits)

            data = response.data()
            self.log.info(f"new_order() response: {data}")
            return data

        except Exception as e:
            self.log.error(e)
            return None

    def _new_margin_order(self, symbol:Symbol, op: OperateType, quantity: float) -> Optional[dict]:
        is_isolated = self.margin_mode == MarginMode.ISOLATED_MARGIN

        try:
            if op == OperateType.SHORT:
                base_asset = symbol.base

                # 检查可借数量
                borrowable_info = self.get_margin_borrowable(base_asset, symbol.name(), is_isolated)
                if not borrowable_info or float(borrowable_info.get('amount', 0)) < quantity:
                    self.log.error(f"Insufficient borrowable amount for {base_asset}. Available: {borrowable_info}")
                    return None

                # 借入资产
                borrow_result = self.borrow_asset(base_asset, quantity, symbol.name(), is_isolated)
                if not borrow_result or 'tranId' not in borrow_result:
                    self.log.error(f"Failed to borrow {base_asset}: {borrow_result}")
                    return None

                # 卖出借入的资产
                result = self.new_margin_order(
                    symbol=symbol.name(),
                    side='SELL',
                    quantity=quantity,
                    is_isolated=is_isolated
                )
                return result

            elif op == OperateType.LONG:
                # 做多：买入
                result = self.new_margin_order(
                    symbol=symbol.name(),
                    side='BUY',
                    quantity=quantity,
                    is_isolated=is_isolated
                )
                return result

            else:
                self.log.warning(f"Unsupported operation type for margin: {op}")
                return None

        except Exception as e:
            self.log.error(f"Margin order failed: {e}")
            return None

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

    def _sign_margin_request(self, params: dict) -> str:
        query_string = urlencode(sorted(params.items()))
        signature = hmac.new(
            self.cfg.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature

    def _margin_api_request(self, method: str, endpoint: str, params: dict = None, signed: bool = True) -> dict:
        if params is None:
            params = {}

        if signed:
            params['timestamp'] = int(time.time() * 1000)
            params['recvWindow'] = RECV_WINDOW * 1000
            params['signature'] = self._sign_margin_request(params)

        url = f"{MARGIN_API_BASE_URL}{endpoint}"
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, params=params, headers={'X-MBX-APIKEY': self.cfg.api_key})
            elif method.upper() == 'POST':
                response = requests.post(url, params=params, headers={'X-MBX-APIKEY': self.cfg.api_key})
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.log.error(f"Margin API request failed: {e}")
            raise

    def borrow_asset(self, asset: str, amount: float, symbol: str = None, is_isolated: bool = False) -> dict:
        """
        借入资产（用于做空）

        Args:
            asset: 要借入的资产名称
            amount: 借入数量
            symbol: 交易对（Isolated Margin 模式下必需）
            is_isolated: 是否为 Isolated Margin
        """
        if self.margin_mode == MarginMode.SPOT:
            self.log.warning("Borrow asset called but margin_mode is SPOT")
            return {}

        params = {
            'asset': asset,
            'amount': amount,
            'isIsolated': 'TRUE' if is_isolated else 'FALSE',
        }

        if is_isolated and symbol:
            params['symbol'] = symbol

        result = self._margin_api_request('POST', '/margin/loan', params)
        self.log.info(f"Borrow asset: {amount} {asset}, symbol={symbol}, isolated={is_isolated}, result: {result}")
        return result

    def get_margin_account(self, symbol: str = None) -> dict:
        """
        查询保证金账户信息
        
        Args:
            symbol: 交易对（Isolated Margin 模式下查询特定交易对）
        """
        if self.margin_mode == MarginMode.SPOT:
            return {}

        params = {}
        if symbol and self.margin_mode == MarginMode.ISOLATED_MARGIN:
            params['symbols'] = symbol

        result = self._margin_api_request('GET', '/margin/account', params)
        return result

    def get_margin_borrowable(self, asset: str, symbol: str = None, is_isolated: bool = False) -> dict:
        """
        查询可借资产信息
        
        Args:
            asset: 资产名称
            symbol: 交易对（Isolated Margin 模式下必需）
            is_isolated: 是否为 Isolated Margin
        """
        if self.margin_mode == MarginMode.SPOT:
            return {}

        params = {
            'asset': asset,
            'isIsolated': 'TRUE' if is_isolated else 'FALSE',
        }
        
        if is_isolated and symbol:
            params['symbol'] = symbol

        result = self._margin_api_request('GET', '/margin/maxBorrowable', params)
        return result

    def new_margin_order(
            self,
            symbol: str,
            side: str,
            quantity: float,
            price: Optional[float] = None,
            order_type: str = "MARKET",
            is_isolated: bool = False,
    ) -> dict:
        """
        创建 Margin 订单

        Args:
            symbol: 交易对
            side: 订单方向 ('BUY' 或 'SELL')
            quantity: 数量
            price: 价格（限价单需要）
            order_type: 订单类型 ('MARKET' 或 'LIMIT')
            is_isolated: 是否为 Isolated Margin
        """
        if self.margin_mode == MarginMode.SPOT:
            self.log.warning("New margin order called but margin_mode is SPOT")
            return {}

        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'isIsolated': 'TRUE' if is_isolated else 'FALSE',
        }

        if order_type == 'MARKET':
            params['quantity'] = quantity
        elif order_type == 'LIMIT':
            params['quantity'] = quantity
            params['price'] = price
            params['timeInForce'] = 'GTC'

        result = self._margin_api_request('POST', '/margin/order', params)
        self.log.info(f"New margin order: {side} {quantity} {symbol}, isolated={is_isolated}, result: {result}")
        return result


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
