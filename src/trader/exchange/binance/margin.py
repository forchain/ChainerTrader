from pydantic import BaseModel

from trader.common.logger import default
from trader.common.singleton import SingletonMeta
from binance_sdk_margin_trading.margin_trading import (
    MarginTrading,
    ConfigurationRestAPI,
    MARGIN_TRADING_REST_API_PROD_URL,
)
from binance_sdk_margin_trading.rest_api.models import MarginAccountNewOrderSideEnum

from trader.exchange.exchange_config import ExchangeConfig
from trader.utils.operate import OperateType
from trader.utils.symbol_interval import Symbol


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
            base_path=cfg.base_path if cfg.base_path is not None else MARGIN_TRADING_REST_API_PROD_URL,
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

    def new_order(self, symbol:Symbol, op: OperateType, quantity: float = 0, auto_borrow: bool = True):
        try:
            side_name = op.name
            if op == OperateType.SHORT:
                side_name = "SELL"
            elif op == OperateType.LONG:
                side_name = "BUY"
            elif op == OperateType.CLOSE:
                side_name = "SELL"
                self.log.warning("CLOSE operation in MARGIN mode mapped to SELL")

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