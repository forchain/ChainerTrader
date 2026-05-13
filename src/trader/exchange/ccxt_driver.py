from __future__ import annotations

from datetime import datetime
from decimal import ROUND_DOWN, Decimal
import os
from typing import Any

try:
    import ccxt  # type: ignore
except Exception:  # pragma: no cover - optional until dependency is installed
    ccxt = None

from trader.common.logger import default
from trader.exchange.balance import Balance
from trader.exchange.exchange_config import ExchangeConfig, MarginMode
from trader.exchange.exchange_type import ExchangeType
from trader.execution.models import ExecutionSide, ExecutionStatus, PositionView, ProtectionIntentType, ProtectionOrderView
from trader.utils.kline import Kline
from trader.utils.operate import OperateType
from trader.utils.symbol_interval import Symbol, SymbolInterval, get_time_duration


class CcxtExchangeDriver:
    KLINE_LIMIT_MAX = 1000
    KLINE_LIMIT_DEFAULT = 500

    def __init__(
        self,
        cfg: ExchangeConfig,
        *,
        client: Any | None = None,
        client_factory: Any | None = None,
        log=default(),
    ):
        self.cfg = cfg
        self.log = log
        self._client_factory = client_factory
        self.client = client or self._build_client()
        self._server_time: float | None = None

    def name(self) -> str:
        return self.cfg.ty.name if hasattr(self.cfg.ty, "name") else ExchangeType.BINANCE.name

    def driver_name(self) -> str:
        return "ccxt"

    def start(self):
        self._ensure_markets_loaded()
        return True

    def stop(self):
        close = getattr(self.client, "close", None)
        if close is not None:
            return close()
        return None

    def ping(self) -> bool:
        try:
            self.time()
            return True
        except Exception as exc:  # pragma: no cover - network path
            self.log.error(exc)
            return False

    def time(self) -> datetime | None:
        fetch_time = getattr(self.client, "fetch_time", None)
        if fetch_time is None:
            return self.server_datetime()
        try:
            self._server_time = float(fetch_time()) / 1000.0
            return self.server_datetime()
        except Exception as exc:  # pragma: no cover - network path
            self.log.error(exc)
            return self.server_datetime()

    def server_datetime(self) -> datetime | None:
        if self._server_time is None:
            return None
        return datetime.fromtimestamp(self._server_time)

    def server_time_offset(self) -> float | None:
        if self._server_time is None:
            return None
        return self._server_time - datetime.now().timestamp()

    def exchange_info(self, symbol: str | None = None):
        self._ensure_markets_loaded()
        if symbol is None:
            return getattr(self.client, "markets", None)
        return self.client.market(self._ccxt_symbol(symbol))

    def get_klines(
        self,
        si: SymbolInterval,
        start_time: int = None,
        end_time: int = None,
        limit: int = KLINE_LIMIT_DEFAULT,
    ) -> list[Kline]:
        market_symbol = self._ccxt_symbol(si.symbol())
        timeframe = si.interval.value
        step = get_time_duration(si.interval)
        r_limit = min(limit, self.KLINE_LIMIT_MAX)
        since_ms = None
        if start_time is not None and start_time > 0:
            since_ms = start_time * 1000
        elif end_time is not None and end_time > 0:
            since_ms = max(0, (end_time - max(r_limit, 1) * step * 2) * 1000)

        rows = self.client.fetch_ohlcv(market_symbol, timeframe, since=since_ms, limit=r_limit)
        return self._rows_to_klines(rows, step, start_time=start_time, end_time=end_time, limit=r_limit)

    def get_latest_klines(self, si: SymbolInterval, limit: int = KLINE_LIMIT_DEFAULT) -> list[Kline]:
        return self.get_klines(si, None, None, limit)

    def get_klines_by_end(
        self,
        si: SymbolInterval,
        end_time: int,
        limit: int = KLINE_LIMIT_DEFAULT,
    ) -> list[Kline]:
        return self.get_klines(si, None, end_time, limit)

    def get_klines_by_start(
        self,
        si: SymbolInterval,
        start_time: int = None,
        limit: int = KLINE_LIMIT_DEFAULT,
    ) -> list[Kline]:
        start_time = start_time or 0
        return self.get_klines(si, start_time, None, limit)

    def get_account(self):
        fetch_balance = getattr(self.client, "fetch_balance", None)
        if fetch_balance is None:
            return None
        params = self._balance_params()
        return fetch_balance(params)

    def get_account_balance(self, asset: str) -> float:
        acct = self.get_account() or {}
        if not isinstance(acct, dict):
            return float(getattr(acct, "free", {}).get(asset, 0.0) or 0.0)
        free = acct.get("free", {}) or {}
        if asset in free:
            return float(free.get(asset, 0.0) or 0.0)
        total = acct.get("total", {}) or {}
        return float(total.get(asset, 0.0) or 0.0)

    def get_account_balances(self) -> list[Balance]:
        acct = self.get_account() or {}
        if not isinstance(acct, dict):
            return []
        free = acct.get("free", {}) or {}
        total = acct.get("total", {}) or {}
        assets = sorted(set(free) | set(total))
        balances: list[Balance] = []
        for asset in assets:
            free_amount = float(free.get(asset, 0.0) or 0.0)
            total_amount = float(total.get(asset, free_amount) or free_amount)
            locked = max(total_amount - free_amount, 0.0)
            balances.append(Balance(asset=asset, free=free_amount, locked=locked))
        return balances

    def get_position_view(self, symbol: Symbol) -> list[PositionView]:
        acct = self.get_account() or {}
        if not isinstance(acct, dict):
            return []
        if self.cfg.margin_mode.value == "spot":
            quantity = self.get_account_balance(symbol.base)
            if quantity > 0:
                return [PositionView(symbol=symbol.name(), side=ExecutionSide.LONG, quantity=quantity)]
            return []

        info = acct.get("info", {}) or {}
        for asset in info.get("userAssets", []) or []:
            if asset.get("asset") != symbol.base:
                continue
            try:
                net_asset = float(asset.get("netAsset", 0.0) or 0.0)
            except (TypeError, ValueError):
                net_asset = 0.0
            if net_asset > 0:
                return [PositionView(symbol=symbol.name(), side=ExecutionSide.LONG, quantity=net_asset)]
            if net_asset < 0:
                return [PositionView(symbol=symbol.name(), side=ExecutionSide.SHORT, quantity=abs(net_asset))]
        return []

    def account_commission(self, symbol: str = None):
        fetch_fee = getattr(self.client, "fetch_trading_fee", None)
        if fetch_fee is None or symbol is None:
            return None
        return fetch_fee(self._ccxt_symbol(symbol))

    def get_account_commission(self, symbol: str) -> float | None:
        commission = self.account_commission(symbol)
        if commission is None:
            return None
        if isinstance(commission, dict):
            taker = commission.get("taker")
            return float(taker) if taker is not None else None
        taker = getattr(commission, "taker", None)
        if taker is not None:
            return float(taker)
        return None

    def new_order(self, symbol: Symbol, op: OperateType, quantity: float = 0):
        return self.client.create_order(
            self._ccxt_symbol(symbol.name()),
            "market",
            self._order_side(op),
            self._normalize_amount(symbol, quantity),
            None,
            self._order_params({"sideEffectType": "AUTO_REPAY"} if op == OperateType.CLOSE else None),
        )

    def new_stop_order(self, symbol: Symbol, op: OperateType, quantity: float, stop_price: float):
        return self._create_trigger_order(symbol, op, quantity, "stopLossPrice", stop_price)

    def new_take_profit_order(self, symbol: Symbol, op: OperateType, quantity: float, limit_price: float):
        return self._create_trigger_order(symbol, op, quantity, "takeProfitPrice", limit_price)

    def new_oco_order(self, symbol: Symbol, op: OperateType, quantity: float, stop_price: float, take_profit_price: float):
        stop_order = self.new_stop_order(symbol, op, quantity, stop_price)
        take_profit_order = self.new_take_profit_order(symbol, op, quantity, take_profit_price)
        return {
            "orderListId": "ccxt-bracket",
            "orders": [
                item for item in (stop_order, take_profit_order) if item is not None
            ],
        }

    def replace_stop_order(self, symbol: Symbol, side: OperateType, order_id: str, quantity: float, stop_price: float):
        cancel = self.cancel_order(symbol, order_id)
        if cancel is None:
            return None
        return self.new_stop_order(symbol, side, quantity, stop_price)

    def cancel_order(self, symbol: Symbol, order_id: str):
        cancel_order = getattr(self.client, "cancel_order", None)
        if cancel_order is None:
            return None
        return cancel_order(order_id, self._ccxt_symbol(symbol.name()), self._margin_order_params())

    def delete_order(self, symbol: str):
        return self.cancel_order(self._symbol_from_any(symbol), symbol)

    def cancel_all_open_orders(self, symbol: Symbol):
        fetch_open_orders = getattr(self.client, "fetch_open_orders", None)
        cancel_order = getattr(self.client, "cancel_order", None)
        if fetch_open_orders is None or cancel_order is None:
            return []
        market_symbol = self._ccxt_symbol(symbol.name())
        canceled = []
        params = self._margin_order_params()
        for order in fetch_open_orders(market_symbol, None, None, params) or []:
            order_id = self._as_dict(order).get("id")
            if order_id:
                canceled.append(cancel_order(str(order_id), market_symbol, params))
        return canceled

    def get_open_orders(self, symbol: Symbol) -> list[dict[str, Any]]:
        fetch_open_orders = getattr(self.client, "fetch_open_orders", None)
        if fetch_open_orders is None:
            return []
        orders = fetch_open_orders(self._ccxt_symbol(symbol.name()), None, None, self._margin_order_params())
        return [self._as_dict(order) for order in orders or []]

    def get_open_protection_orders(self, symbol: Symbol) -> list[ProtectionOrderView]:
        fetch_open_orders = getattr(self.client, "fetch_open_orders", None)
        if fetch_open_orders is None:
            return []
        orders = fetch_open_orders(self._ccxt_symbol(symbol.name()), None, None, self._margin_order_params())
        protection_orders: list[ProtectionOrderView] = []
        grouped: dict[str, list[dict[str, Any]]] = {}
        for order in orders or []:
            order_dict = self._as_dict(order)
            order_list_id = str(order_dict.get("info", {}).get("orderListId") or order_dict.get("orderListId") or "")
            if order_list_id and order_list_id != "-1":
                grouped.setdefault(order_list_id, []).append(order_dict)
                continue
            protection = self._map_protection_order(symbol, order_dict)
            if protection is not None:
                protection_orders.append(protection)
        for order_list_id, legs in grouped.items():
            protection_orders.append(self._map_oco_order(symbol, order_list_id, legs))
        return protection_orders

    def verify_order_ids(self, symbol: Symbol, order_ids: list[str]) -> bool:
        return bool(order_ids) and all(isinstance(order_id, str) and order_id.strip() for order_id in order_ids)

    def auto_repay_for_borrow_block(self, symbol: str) -> dict[str, Any]:
        if self.cfg.margin_mode == MarginMode.SPOT:
            return {"ok": False, "reason": "spot_mode_no_margin_repay"}
        repay_fn = getattr(self.client, "sapiPostMarginRepay", None) or getattr(self.client, "sapi_post_margin_repay", None)
        if repay_fn is None:
            return {"ok": False, "reason": "margin_repay_endpoint_missing"}

        symbol_obj = self._symbol_from_any(symbol)
        assets = [symbol_obj.base, symbol_obj.quote]
        max_repay = float(os.getenv("CHAINERTRADER_MARGIN_AUTO_REPAY_MAX_PER_ASSET", "50") or 50.0)
        min_repay = float(os.getenv("CHAINERTRADER_MARGIN_AUTO_REPAY_MIN_AMOUNT", "0.000001") or 0.000001)

        account = self.get_account() or {}
        info = account.get("info", {}) if isinstance(account, dict) else {}
        user_assets = info.get("userAssets", []) if isinstance(info, dict) else []
        by_asset: dict[str, dict[str, Any]] = {}
        for row in user_assets or []:
            if isinstance(row, dict) and row.get("asset"):
                by_asset[str(row["asset"])] = row

        results: list[dict[str, Any]] = []
        any_repaid = False
        for asset in assets:
            row = by_asset.get(asset, {})
            borrowed = float(row.get("borrowed", 0.0) or 0.0)
            interest = float(row.get("interest", 0.0) or 0.0)
            free = float(row.get("free", 0.0) or 0.0)
            liability = max(borrowed + interest, 0.0)
            repay_amount = min(liability, free, max_repay)
            if repay_amount < min_repay:
                results.append(
                    {
                        "asset": asset,
                        "status": "skipped",
                        "borrowed": borrowed,
                        "interest": interest,
                        "free": free,
                        "reason": "no_repayable_liability_or_free",
                    }
                )
                continue
            try:
                payload = repay_fn({"asset": asset, "amount": self._format_decimal_amount(repay_amount)})
                results.append(
                    {
                        "asset": asset,
                        "status": "repaid",
                        "amount": repay_amount,
                        "borrowed": borrowed,
                        "interest": interest,
                        "free": free,
                        "payload": payload,
                    }
                )
                any_repaid = True
            except Exception as exc:
                results.append(
                    {
                        "asset": asset,
                        "status": "error",
                        "amount": repay_amount,
                        "borrowed": borrowed,
                        "interest": interest,
                        "free": free,
                        "error": str(exc),
                    }
                )
        return {
            "ok": any_repaid,
            "symbol": symbol_obj.name(),
            "max_repay_per_asset": max_repay,
            "results": results,
        }

    def _build_client(self):
        if self._client_factory is not None:
            return self._client_factory(self.cfg)
        if ccxt is None:
            raise ImportError("ccxt is required to use the ccxt exchange driver")
        exchange_id = self.cfg.ty.name.lower() if hasattr(self.cfg.ty, "name") else "binance"
        exchange_cls = getattr(ccxt, exchange_id)
        options = {
            "defaultType": self._default_type(),
            # Keep live smoke routing on spot/margin APIs only.
            # Some ccxt versions probe delivery/futures markets during load_markets
            # unless fetch types are explicitly constrained.
            "fetchMarkets": {"types": ["spot"]},
            # Reduce Binance -1021 timestamp drift failures in live/cleanup paths.
            "adjustForTimeDifference": True,
            "recvWindow": int(os.getenv("CHAINERTRADER_BINANCE_RECV_WINDOW", "20000") or 20000),
        }
        return exchange_cls(
            {
                "apiKey": self.cfg.api_key,
                "secret": self.cfg.api_secret,
                "enableRateLimit": True,
                "timeout": 10000,
                "options": options,
            }
        )

    def _default_type(self) -> str:
        # Binance cross/isolated margin should use spot market type with margin params.
        # Using defaultType=margin may route to futures-like endpoints in some ccxt versions.
        return "spot"

    def _ensure_markets_loaded(self):
        load_markets = getattr(self.client, "load_markets", None)
        if load_markets is not None:
            load_markets()

    def _balance_params(self) -> dict[str, Any]:
        if self.cfg.margin_mode.value == "spot":
            return {}
        return {"type": "margin"}

    def _order_params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(extra or {})
        if self.cfg.margin_mode.value == "cross_margin":
            params.setdefault("marginMode", "cross")
            params.setdefault("sideEffectType", "AUTO_BORROW_REPAY")
        elif self.cfg.margin_mode.value == "isolated_margin":
            params.setdefault("marginMode", "isolated")
            params.setdefault("sideEffectType", "AUTO_BORROW_REPAY")
        return params

    def _margin_order_params(self) -> dict[str, Any]:
        if self.cfg.margin_mode.value == "cross_margin":
            return {"marginMode": "cross"}
        if self.cfg.margin_mode.value == "isolated_margin":
            return {"marginMode": "isolated"}
        return {}

    def _ccxt_symbol(self, symbol: str) -> str:
        if "/" in symbol:
            return symbol
        if "-" in symbol:
            base, quote = symbol.split("-", 1)
            return f"{base}/{quote}"
        for quote in ("USDT", "USDC", "BUSD", "BTC", "ETH"):
            if symbol.endswith(quote) and len(symbol) > len(quote):
                return f"{symbol[:-len(quote)]}/{quote}"
        return symbol

    def _symbol_from_any(self, symbol: str | Symbol) -> Symbol:
        if isinstance(symbol, Symbol):
            return symbol
        if "-" in symbol:
            return Symbol(symbol)
        for quote in ("USDT", "USDC", "BUSD", "BTC", "ETH"):
            if symbol.endswith(quote) and len(symbol) > len(quote):
                return Symbol(f"{symbol[:-len(quote)]}-{quote}")
        return Symbol(symbol)

    def _order_side(self, op: OperateType) -> str:
        if op in (OperateType.BUY, OperateType.LONG):
            return "buy"
        if op == OperateType.CLOSE:
            return "buy" if self.cfg.margin_mode != MarginMode.SPOT else "sell"
        if op in (OperateType.SELL, OperateType.SHORT):
            return "sell"
        return op.name.lower()

    def _normalize_amount(self, symbol: Symbol, quantity: float) -> float:
        market = self._market_for_symbol(symbol)
        precision = self._market_precision(market, "amount")
        limits = self._market_limits(market, "amount")
        normalized = self._floor_to_precision(quantity, precision)
        min_amount = limits.get("min")
        if min_amount is not None and normalized < float(min_amount):
            raise ValueError(f"quantity {normalized} is below min amount {min_amount} for {symbol.name()}")
        return normalized

    def _normalize_price(self, symbol: Symbol, price: float) -> float:
        market = self._market_for_symbol(symbol)
        precision = self._market_precision(market, "price")
        limits = self._market_limits(market, "price")
        normalized = self._floor_to_precision(price, precision)
        min_price = limits.get("min")
        if min_price is not None and normalized < float(min_price):
            raise ValueError(f"price {normalized} is below min price {min_price} for {symbol.name()}")
        return normalized

    def _create_trigger_order(self, symbol: Symbol, op: OperateType, quantity: float, trigger_param: str, trigger_price: float):
        return self.client.create_order(
            self._ccxt_symbol(symbol.name()),
            "market",
            self._order_side(op),
            self._normalize_amount(symbol, quantity),
            None,
            self._order_params({trigger_param: self._normalize_price(symbol, trigger_price)}),
        )

    def _market_for_symbol(self, symbol: Symbol):
        return self.client.market(self._ccxt_symbol(symbol.name()))

    def _market_precision(self, market: Any, key: str) -> int | None:
        if not isinstance(market, dict):
            return None
        precision = market.get("precision", {}) or {}
        value = precision.get(key)
        if isinstance(value, int):
            return value
        return None

    def _market_limits(self, market: Any, key: str) -> dict[str, Any]:
        if not isinstance(market, dict):
            return {}
        limits = market.get("limits", {}) or {}
        return limits.get(key, {}) or {}

    def _floor_to_precision(self, value: float, precision: int | None) -> float:
        if precision is None:
            return float(value)
        quant = Decimal("1").scaleb(-precision)
        return float((Decimal(str(value)) / quant).to_integral_value(rounding=ROUND_DOWN) * quant)

    def _format_decimal_amount(self, value: float) -> str:
        quantized = Decimal(str(value)).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        text = format(quantized, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text

    def _rows_to_klines(
        self,
        rows: list[list[Any]],
        step: int,
        *,
        start_time: int | None,
        end_time: int | None,
        limit: int,
    ) -> list[Kline]:
        klines: list[Kline] = []
        for row in rows or []:
            if len(row) < 6:
                continue
            open_time = int(float(row[0]) / 1000)
            if start_time is not None and open_time < start_time:
                continue
            if end_time is not None and open_time > end_time:
                continue
            close_time = open_time + step - 1
            klines.append(
                Kline(
                    open_time,
                    float(row[1]),
                    float(row[2]),
                    float(row[3]),
                    float(row[4]),
                    close_time,
                    float(row[5]),
                    0.0,
                    0,
                    0.0,
                    0.0,
                    0.0,
                )
            )
        if limit > 0:
            klines = klines[-limit:]
        return klines

    def _as_dict(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        payload = {}
        for key in ("id", "type", "side", "amount", "price", "stopPrice", "status", "info"):
            payload[key] = getattr(value, key, None)
        info = payload.get("info")
        if not isinstance(info, dict):
            payload["info"] = {}
        return payload

    def _map_protection_order(self, symbol: Symbol, order: dict[str, Any]) -> ProtectionOrderView | None:
        order_type = str(order.get("type") or "").lower()
        if "stop" not in order_type and "take_profit" not in order_type:
            return None
        protection_type = (
            ProtectionIntentType.STOP_LOSS
            if "stop" in order_type and "take_profit" not in order_type
            else ProtectionIntentType.TAKE_PROFIT
        )
        stop_price = order.get("stopPrice") or order.get("stop_price")
        take_profit_price = order.get("price") if "take_profit" in order_type else None
        return ProtectionOrderView(
            protection_id=str(order.get("id") or order.get("clientOrderId") or ""),
            symbol=symbol.name(),
            protection_type=protection_type,
            status=ExecutionStatus.ACCEPTED,
            quantity=float(order.get("amount") or 0.0),
            stop_price=float(stop_price) if stop_price is not None else None,
            take_profit_price=float(take_profit_price) if take_profit_price is not None else None,
            exchange_order_ids=(str(order.get("id") or ""),),
            native=False,
            metadata={"ccxt_type": order.get("type")},
        )

    def _map_oco_order(self, symbol: Symbol, order_list_id: str, legs: list[dict[str, Any]]) -> ProtectionOrderView:
        stop_price = None
        take_profit_price = None
        quantity = 0.0
        order_ids: list[str] = []
        for leg in legs:
            order_ids.append(str(leg.get("id") or ""))
            quantity = max(quantity, float(leg.get("amount") or 0.0))
            order_type = str(leg.get("type") or "").lower()
            if "stop" in order_type:
                stop_price = float(leg.get("stopPrice") or leg.get("price") or 0.0)
            elif "take_profit" in order_type or "limit" in order_type:
                take_profit_price = float(leg.get("price") or 0.0)
        return ProtectionOrderView(
            protection_id=f"oco-{order_list_id}",
            symbol=symbol.name(),
            protection_type=ProtectionIntentType.BRACKET,
            status=ExecutionStatus.ACCEPTED,
            quantity=quantity,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            exchange_order_ids=tuple(order_ids),
            native=False,
            metadata={"orderListId": order_list_id},
        )
