"""Exchange account use cases: account views, symbol-scoped cancellation, credential preflight, and routing."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from trader.core.exchange.domain import (
    Balance,
    ExchangeConfig,
    MarginMode,
    OpenOrder,
    UserExchangeContext,
    parse_exchange_config,
)
from trader.core.exchange.exceptions import ExchangeConnectivityError, UserExchangeCredentialError
from trader.core.identity.credentials import mask_api_key
from trader.core.identity.interfaces import SecretCipher
from trader.core.shared.domain import Symbol

MISSING_SERVICE_KEY = "TRADER_SECRET_KEY is required to read user-owned Binance credentials"
MISSING_CREDENTIAL_STORE = "live trading requires a user exchange credential store"


@dataclass(frozen=True)
class AccountView:
    balances: list[Balance]
    open_orders: list[OpenOrder] = field(default_factory=list)
    locked_source: list[OpenOrder] = field(default_factory=list)
    borrow_asset: str = ""
    borrowable_amount: float = 0.0
    operable_amount: float = 0.0
    account_error: str = ""


def base_exchange_config(exchange: Any = None, cfg: Any = None) -> ExchangeConfig:
    exchange_cfg = getattr(exchange, "cfg", None)
    if isinstance(exchange_cfg, ExchangeConfig):
        return exchange_cfg
    raw_exchange_cfg = getattr(cfg, "exchange", "") if cfg is not None else ""
    if raw_exchange_cfg:
        parsed = parse_exchange_config(raw_exchange_cfg)
        if parsed is not None:
            return parsed
    return ExchangeConfig()


def build_user_exchange_context(
    *,
    base_cfg: ExchangeConfig | None,
    credential: Any,
    user_id: int,
    margin_mode: MarginMode,
    cipher: SecretCipher | None,
) -> UserExchangeContext:
    if credential is None:
        raise UserExchangeCredentialError(f"missing BINANCE API credential for user_id={user_id}")
    if cipher is None:
        raise UserExchangeCredentialError(MISSING_SERVICE_KEY)

    api_key = cipher.decrypt(credential.encrypted_api_key)
    api_secret = cipher.decrypt(credential.encrypted_api_secret)
    payload = (base_cfg or ExchangeConfig()).model_dump()
    payload["api_key"] = api_key
    payload["api_secret"] = api_secret
    payload["margin_mode"] = margin_mode
    return UserExchangeContext(
        cfg=ExchangeConfig(**payload),
        user_id=user_id,
        credential_id=getattr(credential, "id", None),
        masked_api_key=str(getattr(credential, "masked_api_key", "") or mask_api_key(api_key)),
    )


def attach_user_exchange_context(exchange: Any, context: UserExchangeContext) -> Any:
    setattr(exchange, "user_id", context.user_id)
    setattr(exchange, "credential_id", context.credential_id)
    setattr(exchange, "masked_api_key", context.masked_api_key)
    return exchange


class PreflightUserExchange:
    """Check the service secret, the user credential, and optional connectivity."""

    def __init__(self, credentials: Any, *, cipher: SecretCipher | None, exchange: str = "BINANCE"):
        self.credentials = credentials
        self.cipher = cipher
        self.exchange = exchange

    async def execute(self, user_id: int, *, connectivity_check: Callable[[Any], bool] | None = None) -> Any:
        if self.cipher is None:
            raise UserExchangeCredentialError(MISSING_SERVICE_KEY)
        if self.credentials is None:
            raise UserExchangeCredentialError(MISSING_CREDENTIAL_STORE)
        credential = self.credentials.get_default(user_id, self.exchange)
        if inspect.isawaitable(credential):
            credential = await credential
        if credential is None:
            raise UserExchangeCredentialError(f"missing BINANCE API credential for user_id={user_id}")
        if connectivity_check is not None and not connectivity_check(credential):
            raise ExchangeConnectivityError(f"invalid BINANCE API credential or connectivity failure for user_id={user_id}")
        return credential


class RouteExchangeForTask:
    """Resolve the task user's credential into a margin-mode-aware exchange client."""

    def __init__(
        self,
        credentials: Any,
        *,
        base_cfg: ExchangeConfig | None,
        cipher: SecretCipher | None,
        exchange_factory: Callable[[ExchangeConfig], Any],
        exchange: str = "BINANCE",
    ):
        self.credentials = credentials
        self.base_cfg = base_cfg
        self.cipher = cipher
        self.exchange_factory = exchange_factory
        self.exchange = exchange

    async def execute(self, user_id: int, *, margin_mode: MarginMode = MarginMode.CROSS_MARGIN) -> Any:
        credential = await PreflightUserExchange(self.credentials, cipher=self.cipher, exchange=self.exchange).execute(user_id)
        context = build_user_exchange_context(
            base_cfg=self.base_cfg,
            credential=credential,
            user_id=user_id,
            margin_mode=margin_mode,
            cipher=self.cipher,
        )
        return attach_user_exchange_context(self.exchange_factory(context.cfg), context)


class SymbolOpenOrders:
    """Symbol-scoped open-order visibility and cancellation (ADR-0001)."""

    def __init__(self, exchange: Any):
        self.exchange = exchange

    def list(self, symbol: Symbol | None) -> list[OpenOrder]:
        return _open_order_rows(self.exchange.get_open_orders(_require_symbol(symbol)) or [])

    def cancel(self, symbol: Symbol | None) -> Any:
        return self.exchange.cancel_all_open_orders(_require_symbol(symbol))


def _require_symbol(symbol: Symbol | None) -> Symbol:
    if symbol is None or symbol.is_empty():
        raise ValueError("an explicit symbol is required to cancel open orders")
    return symbol


class ViewLockedSource:
    """Explain which open orders lock the account's balances."""

    def __init__(self, exchange: Any):
        self.exchange = exchange

    def execute(self, balances: list[Balance], *, symbol_interval: Any = None, quote_asset: str | None = None) -> list[OpenOrder]:
        quote = _quote_asset_for_locked_symbol_search(symbol_interval, quote_asset)
        if quote and quote in _locked_balance_assets(balances):
            try:
                rows = self.exchange.get_all_open_orders() or []
            except Exception:
                rows = []
            if rows:
                return _open_order_rows(rows)
        rows: list[Any] = []
        for order_symbol in open_order_symbols_from_locked_balances(balances, symbol=symbol_interval, quote_asset=quote):
            rows.extend(self.exchange.get_open_orders(order_symbol) or [])
        return _open_order_rows(rows)


class BuildAccountView:
    def __init__(self, exchange: Any = None, *, symbol_interval: Any = None, logger: Any = None):
        self.exchange = exchange
        self.symbol_interval = symbol_interval
        self.logger = logger

    def execute(self, *, include_open_orders: bool = True) -> AccountView:
        if self.exchange is None:
            return AccountView(balances=[])

        errors: list[str] = []
        try:
            balances = list(self.exchange.get_account_balances())
        except Exception as exc:
            self._log_error("exchange balance", exc)
            return AccountView(balances=[], account_error=f"交易所账户读取失败: {exc}")

        borrow_asset = _borrow_asset_from_exchange(self.exchange, balances, self.symbol_interval)
        try:
            borrowable_amount = _get_max_borrowable_amount(self.exchange, borrow_asset)
        except Exception as exc:
            borrowable_amount = 0.0
            errors.append(f"最大可借额度读取失败: {exc}")
            self._log_error("max borrowable", exc)

        open_orders: list[OpenOrder] = []
        if include_open_orders:
            try:
                open_orders = ViewLockedSource(self.exchange).execute(
                    balances,
                    symbol_interval=self.symbol_interval,
                    quote_asset=borrow_asset,
                )
            except Exception as exc:
                errors.append(f"开放订单读取失败: {exc}")
                self._log_error("locked orders", exc)

        operable_amount = _operable_amount(balances, borrow_asset, borrowable_amount)
        for balance in balances:
            if balance.asset == borrow_asset:
                balance.max_borrowable = borrowable_amount
                balance.operable = operable_amount
                break

        return AccountView(
            balances=balances,
            open_orders=open_orders,
            locked_source=list(open_orders),
            borrow_asset=borrow_asset,
            borrowable_amount=borrowable_amount,
            operable_amount=operable_amount,
            account_error="；".join(errors),
        )

    def _log_error(self, operation: str, exc: Exception) -> None:
        logger = self.logger
        if logger is not None and hasattr(logger, "error"):
            logger.error(f"account page {operation} read failed: {exc}")


def _borrow_asset_from_exchange(exchange: Any, balances: list[Balance], symbol: Any = None) -> str:
    if symbol is not None:
        quote = getattr(getattr(symbol, "sy", None), "quote", None)
        if quote:
            return str(quote).upper()
    margin_mode = getattr(exchange, "margin_mode", None)
    if margin_mode is not None and getattr(margin_mode, "value", "") != "spot":
        return str(getattr(exchange, "borrow_asset", None) or "USDT").upper()
    if balances:
        for balance in balances:
            if balance.asset == "USDT":
                return "USDT"
        return balances[0].asset
    return "USDT"


def _get_max_borrowable_amount(exchange: Any, asset: str) -> float:
    payload = exchange.get_max_borrowable(asset)
    if isinstance(payload, dict):
        return float(payload.get("amount", 0.0) or 0.0)
    return float(getattr(payload, "amount", 0.0) or 0.0)


def open_order_symbols_from_locked_balances(
    balances: list[Balance],
    *,
    symbol: Any = None,
    quote_asset: str | None = None,
) -> list[Symbol]:
    locked_assets = _locked_balance_assets(balances)
    if not locked_assets:
        return []
    quote = _quote_asset_for_locked_symbol_search(symbol, quote_asset)
    if not quote:
        return []

    ret: list[Symbol] = []
    seen: set[str] = set()

    current_symbol = _symbol_from_symbol_interval(symbol)
    if current_symbol is not None and {current_symbol.base, current_symbol.quote} & set(locked_assets):
        _append_symbol_once(ret, seen, current_symbol)

    for asset in locked_assets:
        if asset == quote:
            continue
        _append_symbol_once(ret, seen, Symbol(f"{asset}-{quote}"))
    return ret


def _locked_balance_assets(balances: list[Balance]) -> list[str]:
    ret: list[str] = []
    seen: set[str] = set()
    for balance in balances:
        try:
            locked = float(balance.locked or 0.0)
        except (TypeError, ValueError):
            continue
        asset = str(balance.asset or "").strip().upper()
        if locked <= 0 or not asset or asset in seen:
            continue
        seen.add(asset)
        ret.append(asset)
    return ret


def _quote_asset_for_locked_symbol_search(symbol: Any = None, quote_asset: str | None = None) -> str:
    current_symbol = _symbol_from_symbol_interval(symbol)
    if current_symbol is not None and current_symbol.quote:
        return current_symbol.quote
    return str(quote_asset or "USDT").strip().upper()


def _symbol_from_symbol_interval(symbol: Any = None) -> Symbol | None:
    if symbol is None:
        return None
    if isinstance(symbol, Symbol):
        return symbol
    if hasattr(symbol, "sy"):
        base = str(getattr(symbol.sy, "base", "") or "").strip().upper()
        quote = str(getattr(symbol.sy, "quote", "") or "").strip().upper()
        if base and quote:
            return Symbol(f"{base}-{quote}")
    return None


def _append_symbol_once(ret: list[Symbol], seen: set[str], symbol: Symbol) -> None:
    name = symbol.name()
    if not name or name in seen:
        return
    seen.add(name)
    ret.append(symbol)


def _open_order_rows(rows: Any) -> list[OpenOrder]:
    orders: list[OpenOrder] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        info = row.get("info") if isinstance(row.get("info"), dict) else {}
        symbol = str(row.get("symbol") or info.get("symbol") or "").replace("/", "")
        order_id = row.get("orderId") or row.get("order_id") or row.get("id") or info.get("orderId") or info.get("order_id")
        orders.append(
            OpenOrder(
                symbol=symbol,
                side=str(row.get("side") or info.get("side") or ""),
                quantity=float(row.get("origQty") or row.get("amount") or row.get("quantity") or 0.0),
                order_id=str(order_id or ""),
                order_type=str(row.get("type") or info.get("type") or ""),
                price=float(row.get("price") or 0.0),
                status=str(row.get("status") or info.get("status") or ""),
            )
        )
    return orders


def _operable_amount(balances: list[Balance], borrow_asset: str, borrowable_amount: float) -> float:
    free_balance = 0.0
    for balance in balances:
        if balance.asset == borrow_asset:
            free_balance = float(balance.free or 0.0)
            break
    return free_balance + float(borrowable_amount or 0.0)
