from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from binance_common.configuration import ConfigurationRestAPI
from binance_common.constants import SPOT_REST_API_PROD_URL
from binance_common.models import RateLimit
from binance_sdk_spot import Spot
from binance_sdk_spot.rest_api.models import (
    AccountCommissionResponse,
    NewOrderSideEnum,
    NewOrderTypeEnum,
    OrderOcoSideEnum,
    OrderCancelReplaceSideEnum,
    OrderCancelReplaceTypeEnum,
    OrderCancelReplaceCancelReplaceModeEnum,
)
import requests
import time
import hmac
import hashlib
from urllib.parse import urlencode, urlparse

from trader.common.logger import default
from trader.exchange.balance import Balance
from trader.exchange.binance.margin import MarginTradingManager
from trader.exchange.exchange_config import ExchangeConfig, MarginMode
from trader.exchange.exchange_type import ExchangeType
from trader.execution.models import (
    PositionView,
    ProtectionOrderView,
    ExecutionSide,
    ProtectionIntentType,
    ExecutionStatus,
)
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

        if self._has_valid_margin_base_path():
            MarginTradingManager(self.cfg, self.log).get_summary_of_margin_account()
        else:
            self.log.info("Skip margin summary: margin base_path is not configured with an absolute URL")
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

    def _has_valid_margin_base_path(self) -> bool:
        base_path = getattr(self.cfg, "base_path", None)
        if not base_path:
            return False

        parsed = urlparse(base_path)
        return bool(parsed.scheme and parsed.netloc)

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
            self.log.info(
                f"get klines: {si.symbol()} {si.interval.value} {len(kls)}/{len(ret)} start={kls[0].open_datetime()} end={kls[len(kls)-1].close_datetime()}"
            )
        else:
            self.log.info(f"get klines: {si.symbol()} {si.interval.value} 0/{len(ret)}")

        return kls

    def get_latest_klines(self, si: SymbolInterval, limit: int = KLINE_LIMIT_DEFAULT) -> list[Kline]:
        return self.get_klines(si, None, None, limit)

    def get_klines_by_end(
        self,
        si: SymbolInterval,
        end_time: int,
        limit: int = KLINE_LIMIT_DEFAULT,
    ) -> list[Kline]:
        r_limit = min(limit, KLINE_LIMIT_MAX)
        try:
            rsp = self.spot_client.rest_api.klines(
                si.symbol(),
                si.interval.value,
                end_time=end_time * 1000,
                limit=r_limit,
            )
            ret = rsp.data()
        except Exception as e:
            self.log.error(f"{e}")
            return None

        kls = parse_klines(ret)
        if kls and len(kls) > 0:
            self.log.info(
                f"get klines by end: {si.symbol()} {si.interval.value} {len(kls)}/{len(ret)} start={kls[0].open_datetime()} end={kls[len(kls)-1].close_datetime()}"
            )
        else:
            self.log.info(f"get klines by end: {si.symbol()} {si.interval.value} 0/{len(ret)}")
        return kls

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

    def get_position_view(self, symbol: Symbol) -> list[PositionView]:
        if self.margin_mode != MarginMode.SPOT:
            return MarginTradingManager(self.cfg, self.log).get_position_view(symbol)

        balance = self.get_account_balance(symbol.base)
        if balance > 0:
            return [
                PositionView(
                    symbol=symbol.name(),
                    side=ExecutionSide.LONG,
                    quantity=balance,
                )
            ]
        return []

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

    def new_order(self, symbol: Symbol, op: OperateType, quantity: float = 0):
        if self.has_rate_limit("ORDERS"):
            self.log.error("Rate limit")
            return None

        if self.margin_mode != MarginMode.SPOT:
            return self.new_margin_order(symbol, op, quantity)

        try:
            quantity = self._normalize_quantity(symbol, quantity)
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

    def new_oco_order(self, symbol: Symbol, op: OperateType, quantity: float, stop_price: float, take_profit_price: float):
        if self.has_rate_limit("ORDERS"):
            self.log.error("Rate limit")
            return None

        if self.margin_mode != MarginMode.SPOT:
            return MarginTradingManager(self.cfg, self.log).new_oco_order(
                symbol,
                op,
                self._normalize_quantity(symbol, quantity),
                self._normalize_price(symbol, stop_price),
                self._normalize_price(symbol, take_profit_price),
            )

        try:
            quantity = self._normalize_quantity(symbol, quantity)
            stop_price = self._normalize_price(symbol, stop_price)
            take_profit_price = self._normalize_price(symbol, take_profit_price)
            side_name = protection_side_name(op)
            # OCO price: Take Profit limit price
            # OCO stopPrice: Stop Loss trigger price
            response = self.spot_client.rest_api.order_oco(
                symbol=symbol.name(),
                side=OrderOcoSideEnum[side_name].value,
                quantity=quantity,
                price=take_profit_price,
                stop_price=stop_price,
            )

            data = response.data()
            self.log.info(f"new_oco_order() response: {data}")
            return data
        except Exception as e:
            self.log.error(f"new_oco_order() error: {e}")
            return None

    def new_stop_order(self, symbol: Symbol, op: OperateType, quantity: float, stop_price: float):
        if self.has_rate_limit("ORDERS"):
            self.log.error("Rate limit")
            return None

        if self.margin_mode != MarginMode.SPOT:
            return MarginTradingManager(self.cfg, self.log).new_stop_order(
                symbol,
                op,
                self._normalize_quantity(symbol, quantity),
                self._normalize_price(symbol, stop_price),
            )

        try:
            quantity = self._normalize_quantity(symbol, quantity)
            stop_price = self._normalize_price(symbol, stop_price)
            side_name = protection_side_name(op)
            response = self.spot_client.rest_api.new_order(
                symbol=symbol.name(),
                side=NewOrderSideEnum[side_name].value,
                type=NewOrderTypeEnum["STOP_LOSS"].value,
                quantity=quantity,
                stop_price=stop_price,
            )
            data = response.data()
            self.log.info(f"new_stop_order() response: {data}")
            return data
        except Exception as e:
            self.log.error(f"new_stop_order() error: {e}")
            return None

    def new_take_profit_order(self, symbol: Symbol, op: OperateType, quantity: float, limit_price: float):
        if self.has_rate_limit("ORDERS"):
            self.log.error("Rate limit")
            return None

        if self.margin_mode != MarginMode.SPOT:
            return MarginTradingManager(self.cfg, self.log).new_take_profit_order(
                symbol,
                op,
                self._normalize_quantity(symbol, quantity),
                self._normalize_price(symbol, limit_price),
            )

        try:
            quantity = self._normalize_quantity(symbol, quantity)
            limit_price = self._normalize_price(symbol, limit_price)
            side_name = protection_side_name(op)
            response = self.spot_client.rest_api.new_order(
                symbol=symbol.name(),
                side=NewOrderSideEnum[side_name].value,
                type=NewOrderTypeEnum["TAKE_PROFIT"].value,
                quantity=quantity,
                stop_price=limit_price,
            )
            data = response.data()
            self.log.info(f"new_take_profit_order() response: {data}")
            return data
        except Exception as e:
            self.log.error(f"new_take_profit_order() error: {e}")
            return None

    def replace_stop_order(self, symbol: Symbol, side: OperateType, order_id: str, quantity: float, stop_price: float):
        if self.has_rate_limit("ORDERS"):
            self.log.error("Rate limit")
            return None

        if self.margin_mode != MarginMode.SPOT:
            manager = MarginTradingManager(self.cfg, self.log)
            cancel = getattr(manager, "cancel_order", None)
            if cancel is not None:
                cancel(symbol, order_id)
            return manager.new_stop_order(
                symbol,
                side,
                self._normalize_quantity(symbol, quantity),
                self._normalize_price(symbol, stop_price),
            )

        try:
            quantity = self._normalize_quantity(symbol, quantity)
            stop_price = self._normalize_price(symbol, stop_price)
            side_name = protection_side_name(side)
            
            response = self.spot_client.rest_api.order_cancel_replace(
                symbol=symbol.name(),
                side=OrderCancelReplaceSideEnum[side_name].value,
                type=OrderCancelReplaceTypeEnum["STOP_LOSS"].value,
                cancel_replace_mode=OrderCancelReplaceCancelReplaceModeEnum["STOP_ON_FAILURE"].value,
                cancel_order_id=int(order_id),
                quantity=quantity,
                stop_price=stop_price,
            )
            data = response.data()
            self.log.info(f"replace_stop_order() response: {data}")
            return data
        except Exception as e:
            self.log.error(f"replace_stop_order() error: {e}")
            return None

    def is_cross_margin_ready(self) -> bool:
        if self.margin_mode != MarginMode.CROSS_MARGIN:
            return False
        if not self._has_valid_margin_base_path():
            self.log.warning("Cross margin is not ready: margin base_path is not configured with an absolute URL")
            return False
        return True

    def new_margin_order(self, symbol: Symbol, op: OperateType, quantity: float = 0):
        if self.has_rate_limit("ORDERS"):
            self.log.error("Rate limit")
            return None
        if not self.is_cross_margin_ready():
            self.log.warning(f"Skip margin order because cross margin is not ready: symbol={symbol.name()} operateType={op}")
            return None
        return MarginTradingManager(self.cfg, self.log).new_order(symbol, op, self._normalize_quantity(symbol, quantity))

    def get_open_protection_orders(self, symbol: Symbol) -> list[ProtectionOrderView]:
        if self.margin_mode != MarginMode.SPOT:
            return MarginTradingManager(self.cfg, self.log).get_open_protection_orders(symbol)

        try:
            # Get open orders for the symbol
            response = self.spot_client.rest_api.get_open_orders(symbol=symbol.name())
            open_orders = response.data()
            
            protection_orders = []
            
            # Group by orderListId for OCO
            ocos = {}
            
            for order in open_orders:
                # Binance Spot get_open_orders returns list of individual orders.
                # OCO orders have orderListId != -1
                order_list_id = getattr(order, "order_list_id", -1)
                if order_list_id != -1:
                    if order_list_id not in ocos:
                        ocos[order_list_id] = []
                    ocos[order_list_id].append(order)
                    continue

                # Non-OCO protection orders
                if order.type in ("STOP_LOSS", "STOP_LOSS_LIMIT", "TAKE_PROFIT", "TAKE_PROFIT_LIMIT"):
                    protection_type = ProtectionIntentType.STOP_LOSS if "STOP" in order.type else ProtectionIntentType.TAKE_PROFIT
                    protection_orders.append(
                        ProtectionOrderView(
                            protection_id=str(order.order_id),
                            symbol=symbol.name(),
                            protection_type=protection_type,
                            status=ExecutionStatus.ACCEPTED, # If it's in open orders, it's accepted/active
                            quantity=float(order.orig_qty),
                            stop_price=float(order.stop_price) if hasattr(order, "stop_price") and order.stop_price else None,
                            take_profit_price=float(order.price) if "TAKE_PROFIT" in order.type else None,
                            exchange_order_ids=(str(order.order_id),),
                            native=True,
                        )
                    )
            
            # Process OCOs
            for order_list_id, legs in ocos.items():
                # OCO usually has one stop leg and one LIMIT_MAKER take-profit leg.
                stop_price = None
                tp_price = None
                qty = 0.0
                order_ids = []
                for leg in legs:
                    order_ids.append(str(leg.order_id))
                    qty = max(qty, float(leg.orig_qty))
                    if leg.type in ("STOP_LOSS", "STOP_LOSS_LIMIT"):
                        stop_price = float(leg.stop_price)
                    elif leg.type == "LIMIT_MAKER":
                        tp_price = float(leg.price)
                
                protection_orders.append(
                    ProtectionOrderView(
                        protection_id=f"oco-{order_list_id}",
                        symbol=symbol.name(),
                        protection_type=ProtectionIntentType.BRACKET,
                        status=ExecutionStatus.ACCEPTED,
                        quantity=qty,
                        stop_price=stop_price,
                        take_profit_price=tp_price,
                        exchange_order_ids=tuple(order_ids),
                        native=True,
                        metadata={"orderListId": order_list_id}
                    )
                )

            return protection_orders
        except Exception as e:
            self.log.error(f"get_open_protection_orders() error: {e}")
            return []

    def verify_order_ids(self, symbol: Symbol, order_ids: list[str]) -> bool:
        if self.margin_mode != MarginMode.SPOT:
            manager = MarginTradingManager(self.cfg, self.log)
            if hasattr(manager, "verify_order_ids"):
                return manager.verify_order_ids(symbol, order_ids)

        if not order_ids:
            return False
        # For now, we trust that if we got IDs back from an order placement, they are valid.
        return all(isinstance(oid, str) and len(oid) > 0 for oid in order_ids)

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

    def _normalize_quantity(self, symbol: Symbol, quantity: float) -> float:
        try:
            info = self.exchange_info(symbol.name())
            info = _unwrap_actual_instance(info)
            symbols = getattr(info, "symbols", None) or (info.get("symbols") if isinstance(info, dict) else None) or []
            filters = []
            if symbols:
                first = _unwrap_actual_instance(symbols[0])
                filters = getattr(first, "filters", None) or (first.get("filters") if isinstance(first, dict) else None) or []
            for item in filters:
                item = _unwrap_actual_instance(item)
                filter_type = getattr(item, "filter_type", None) or getattr(item, "filterType", None)
                if isinstance(item, dict):
                    filter_type = item.get("filterType") or item.get("filter_type")
                if filter_type != "LOT_SIZE":
                    continue
                step = getattr(item, "step_size", None) or getattr(item, "stepSize", None)
                min_qty = getattr(item, "min_qty", None) or getattr(item, "minQty", None)
                if isinstance(item, dict):
                    step = item.get("stepSize") or item.get("step_size")
                    min_qty = item.get("minQty") or item.get("min_qty")
                normalized = _floor_to_step(Decimal(str(quantity)), Decimal(str(step)))
                if min_qty is not None and normalized < Decimal(str(min_qty)):
                    raise ValueError(f"quantity {normalized} is below minQty {min_qty} for {symbol.name()}")
                return float(normalized)
        except Exception as exc:
            self.log.warning(f"Skip quantity normalization for {symbol.name()}: {exc}")
        return float(quantity)

    def _normalize_price(self, symbol: Symbol, price: float) -> float:
        try:
            info = self.exchange_info(symbol.name())
            info = _unwrap_actual_instance(info)
            symbols = getattr(info, "symbols", None) or (info.get("symbols") if isinstance(info, dict) else None) or []
            filters = []
            if symbols:
                first = _unwrap_actual_instance(symbols[0])
                filters = getattr(first, "filters", None) or (first.get("filters") if isinstance(first, dict) else None) or []
            for item in filters:
                item = _unwrap_actual_instance(item)
                filter_type = getattr(item, "filter_type", None) or getattr(item, "filterType", None)
                if isinstance(item, dict):
                    filter_type = item.get("filterType") or item.get("filter_type")
                if filter_type != "PRICE_FILTER":
                    continue
                tick = getattr(item, "tick_size", None) or getattr(item, "tickSize", None)
                min_price = getattr(item, "min_price", None) or getattr(item, "minPrice", None)
                if isinstance(item, dict):
                    tick = item.get("tickSize") or item.get("tick_size")
                    min_price = item.get("minPrice") or item.get("min_price")
                normalized = _floor_to_step(Decimal(str(price)), Decimal(str(tick)))
                if min_price is not None and normalized < Decimal(str(min_price)):
                    raise ValueError(f"price {normalized} is below minPrice {min_price} for {symbol.name()}")
                return float(normalized)
        except Exception as exc:
            self.log.warning(f"Skip price normalization for {symbol.name()}: {exc}")
        return float(price)


def protection_side_name(op: OperateType) -> str:
    if op in (OperateType.SELL, OperateType.SHORT):
        return "SELL"
    if op in (OperateType.BUY, OperateType.LONG, OperateType.CLOSE):
        return "BUY"
    return op.name


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def _unwrap_actual_instance(value):
    actual_instance = getattr(value, "actual_instance", None)
    if actual_instance is not None and actual_instance is not value:
        return actual_instance
    return value


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
