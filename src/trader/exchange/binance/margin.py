from pydantic import BaseModel

from trader.common.logger import default
from trader.common.singleton import SingletonMeta
from binance_sdk_margin_trading.margin_trading import (
    MarginTrading,
    ConfigurationRestAPI,
    MARGIN_TRADING_REST_API_PROD_URL,
)
from binance_sdk_margin_trading.rest_api.models import MarginAccountNewOrderSideEnum, MarginAccountNewOcoSideEnum

from trader.exchange.exchange_config import ExchangeConfig
from trader.execution.models import (
    PositionView,
    ProtectionOrderView,
    ExecutionSide,
    ProtectionIntentType,
    ExecutionStatus,
)
from trader.utils.operate import OperateType
from trader.utils.symbol_interval import Symbol


def protection_side_name(op: OperateType) -> str:
    if op in (OperateType.SELL, OperateType.SHORT):
        return "SELL"
    if op in (OperateType.BUY, OperateType.LONG, OperateType.CLOSE):
        return "BUY"
    return op.name


class SummaryOfMarginAccount(BaseModel):
    normal_bar:str
    margin_call_bar:str
    force_liquidation_bar:str


class MarginTradingManager(metaclass=SingletonMeta):
    def __init__(self,cfg: ExchangeConfig|None=None,log=default()):
        if cfg is None:
            return
        self.cfg = cfg
        self.log = log

        configuration_rest_api = ConfigurationRestAPI(
            api_key=cfg.api_key,
            api_secret=cfg.api_secret,
            base_path=(
                cfg.margin_base_path
                if getattr(cfg, "margin_base_path", None)
                else (cfg.base_path if cfg.base_path is not None else MARGIN_TRADING_REST_API_PROD_URL)
            ),
            timeout=10000,
            backoff=1,
        )

        self.client = MarginTrading(config_rest_api=configuration_rest_api)

        self.rate_limits=None
        self.summary_account = None

    def get_summary_of_margin_account(self):
        try:
            response = self.client.rest_api.get_summary_of_margin_account()

            self.rate_limits = response.rate_limits
            self.log.info(f"get_summary_of_margin_account() rate limits: {self.rate_limits}")

            data = response.data()
            self.summary_account = SummaryOfMarginAccount(normal_bar=data.normal_bar,margin_call_bar=data.margin_call_bar,force_liquidation_bar=data.force_liquidation_bar)
            self.log.info(f"get_summary_of_margin_account() response: {data}")
        except Exception as e:
            self.log.error(f"get_summary_of_margin_account() error: {e}")

    def query_cross_margin_fee_data(self):
        try:
            response = self.client.rest_api.query_cross_margin_fee_data()

            self.rate_limits = response.rate_limits
            self.log.info(f"query_cross_margin_fee_data() rate limits: {self.rate_limits}")

            data = response.data()
            self.log.info(f"query_cross_margin_fee_data() response: {data}")
        except Exception as e:
            self.log.error(f"query_cross_margin_fee_data() error: {e}")

    def query_cross_margin_account_details(self):
        try:
            response = self.client.rest_api.query_cross_margin_account_details()

            self.rate_limits = response.rate_limits
            if self.rate_limits:
                self.log.info(f"query_cross_margin_account_details() rate limits: {self.rate_limits}")

            data = response.data()
            self.log.info(f"query_cross_margin_account_details() response: {data}")
            return data
        except Exception as e:
            self.log.error(f"query_cross_margin_account_details() error: {e}")
            return None

    def get_margin_account_balance(self, asset: str) -> float:
        account_details = self.query_cross_margin_account_details()
        if account_details and hasattr(account_details, 'user_assets') and account_details.user_assets:
            for user_asset in account_details.user_assets:
                if user_asset.asset == asset:
                    if user_asset.free:
                        return float(user_asset.free)
        return 0.0

    def get_position_view(self, symbol: Symbol) -> list[PositionView]:
        account_details = self.query_cross_margin_account_details()
        if not account_details or not hasattr(account_details, 'user_assets') or not account_details.user_assets:
            return []

        for user_asset in account_details.user_assets:
            if user_asset.asset == symbol.base:
                net_asset = float(user_asset.net_asset) if hasattr(user_asset, 'net_asset') else 0.0
                if abs(net_asset) > 0:
                    side = ExecutionSide.LONG if net_asset > 0 else ExecutionSide.SHORT
                    return [
                        PositionView(
                            symbol=symbol.name(),
                            side=side,
                            quantity=abs(net_asset),
                            metadata={"free": user_asset.free, "borrowed": user_asset.borrowed, "interest": user_asset.interest}
                        )
                    ]
        return []

    def new_order(self, symbol:Symbol, op: OperateType, quantity: float = 0, auto_borrow: bool = True):
        try:
            side_name = op.name
            if op == OperateType.SHORT:
                side_name = "SELL"
            elif op == OperateType.LONG:
                side_name = "BUY"
            elif op == OperateType.CLOSE:
                side_name = "BUY"

            if side_name not in ["BUY", "SELL"]:
                self.log.error(f"Unsupported OperateType: {op.name}")
                return None

            side_effect_type = "AUTO_BORROW_REPAY" if auto_borrow else "NO_SIDE_EFFECT"
            
            if auto_borrow:
                self.log.info(f"Using AUTO_BORROW_REPAY: will automatically borrow if balance is insufficient")
            else:
                required_asset = symbol.quote if side_name == "BUY" else symbol.base
                balance = self.get_margin_account_balance(required_asset)
                self.log.info(f"Balance check: {required_asset} = {balance}, required quantity = {quantity}")
                if balance < quantity:
                    self.log.warning(f"Insufficient balance: {balance} < {quantity}. Order may fail without auto borrow.")

            response = self.client.rest_api.margin_account_new_order(
                symbol=symbol.name(),
                side=MarginAccountNewOrderSideEnum[side_name].value,
                type="MARKET",
                quantity=quantity,
                side_effect_type=side_effect_type,
                auto_repay_at_cancel=False,
            )

            self.rate_limits = response.rate_limits
            if self.rate_limits:
                self.log.info(f"new_order() rate limits: {self.rate_limits}")

            data = response.data()
            self.log.info(f"new_order() response: {data}")
            return data

        except Exception as e:
            self.log.error(f"new_order() error: {e}")
            return None

    def new_oco_order(self, symbol: Symbol, op: OperateType, quantity: float, stop_price: float, take_profit_price: float, auto_borrow: bool = True):
        try:
            side_name = protection_side_name(op)
            side_effect_type = "AUTO_BORROW_REPAY" if auto_borrow else "NO_SIDE_EFFECT"

            response = self.client.rest_api.margin_account_new_oco(
                symbol=symbol.name(),
                side=MarginAccountNewOcoSideEnum[side_name].value,
                quantity=quantity,
                price=take_profit_price,
                stop_price=stop_price,
                side_effect_type=side_effect_type,
            )

            data = response.data()
            self.log.info(f"new_oco_order() response: {data}")
            return data
        except Exception as e:
            self.log.error(f"new_oco_order() error: {e}")
            return None

    def new_stop_order(self, symbol: Symbol, op: OperateType, quantity: float, stop_price: float, auto_borrow: bool = True):
        return self._new_protection_order(symbol, op, quantity, "STOP_LOSS", stop_price, auto_borrow=auto_borrow)

    def new_take_profit_order(self, symbol: Symbol, op: OperateType, quantity: float, stop_price: float, auto_borrow: bool = True):
        return self._new_protection_order(symbol, op, quantity, "TAKE_PROFIT", stop_price, auto_borrow=auto_borrow)

    def replace_stop_order(self, symbol: Symbol, op: OperateType, order_id: str, quantity: float, stop_price: float, auto_borrow: bool = True):
        cancel = getattr(self, "cancel_order", None)
        if cancel is not None:
            cancel(symbol, order_id)
        return self.new_stop_order(symbol, op, quantity, stop_price, auto_borrow=auto_borrow)

    def cancel_order(self, symbol: Symbol, order_id: str):
        try:
            response = self.client.rest_api.margin_account_cancel_order(symbol=symbol.name(), order_id=int(order_id))
            data = response.data()
            self.log.info(f"cancel_order() response: {data}")
            return data
        except Exception as e:
            self.log.error(f"cancel_order() error: {e}")
            return None

    def cancel_all_open_orders(self, symbol: Symbol):
        try:
            response = self.client.rest_api.margin_account_cancel_all_open_orders_on_a_symbol(symbol=symbol.name())
            data = response.data()
            self.log.info(f"cancel_all_open_orders() response: {data}")
            return data
        except Exception as e:
            self.log.error(f"cancel_all_open_orders() error: {e}")
            return None

    def _new_protection_order(
        self,
        symbol: Symbol,
        op: OperateType,
        quantity: float,
        order_type: str,
        stop_price: float,
        *,
        auto_borrow: bool = True,
    ):
        try:
            side_effect_type = "AUTO_BORROW_REPAY" if auto_borrow else "NO_SIDE_EFFECT"
            response = self.client.rest_api.margin_account_new_order(
                symbol=symbol.name(),
                side=MarginAccountNewOrderSideEnum[protection_side_name(op)].value,
                type=order_type,
                quantity=quantity,
                stop_price=stop_price,
                side_effect_type=side_effect_type,
                auto_repay_at_cancel=False,
            )
            self.rate_limits = response.rate_limits
            if self.rate_limits:
                self.log.info(f"new_protection_order() rate limits: {self.rate_limits}")
            data = response.data()
            self.log.info(f"new_protection_order() response: {data}")
            return data
        except Exception as e:
            self.log.error(f"new_protection_order() error: {e}")
            return None

    def get_open_protection_orders(self, symbol: Symbol) -> list[ProtectionOrderView]:
        try:
            # Query open margin orders
            response = self.client.rest_api.query_margin_accounts_open_orders(symbol=symbol.name())
            open_orders = response.data()

            protection_orders = []
            
            # Group by orderListId for OCO
            ocos = {}

            for order in open_orders:
                order_list_id = getattr(order, "order_list_id", -1)
                if order_list_id != -1:
                    if order_list_id not in ocos:
                        ocos[order_list_id] = []
                    ocos[order_list_id].append(order)
                    continue

                if order.type in ("STOP_LOSS", "STOP_LOSS_LIMIT", "TAKE_PROFIT", "TAKE_PROFIT_LIMIT"):
                    protection_type = ProtectionIntentType.STOP_LOSS if "STOP" in order.type else ProtectionIntentType.TAKE_PROFIT
                    protection_orders.append(
                        ProtectionOrderView(
                            protection_id=str(order.order_id),
                            symbol=symbol.name(),
                            protection_type=protection_type,
                            status=ExecutionStatus.ACCEPTED,
                            quantity=float(order.orig_qty),
                            stop_price=float(order.stop_price) if hasattr(order, "stop_price") and order.stop_price else None,
                            take_profit_price=float(order.price) if "TAKE_PROFIT" in order.type else None,
                            exchange_order_ids=(str(order.order_id),),
                            native=True,
                        )
                    )
            
            # Process OCOs
            for order_list_id, legs in ocos.items():
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
