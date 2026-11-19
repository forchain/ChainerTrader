"""Deep live-account and open-order lifecycle module.

Owns mode-aware exchange routing, credential decryption, operable capacity,
and ADR-0001 open-order preview/cleanup behind one exchange port seam.

This module lives in the exchange bounded context of ``trader.core`` so the
account lifecycle depends on domain types and ports only, never on concrete
exchange adapters.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Protocol

from trader.core.exchange.domain import Balance, ExchangeConfig, MarginMode, UserExchangeContext
from trader.core.exchange.use_cases import attach_user_exchange_context, base_exchange_config
from trader.core.identity.credentials import mask_api_key
from trader.core.identity.interfaces import SecretCipher
from trader.core.shared.domain import Symbol
from trader.core.task.domain import task_requires_short_capability

# Quote assets used to split compact symbols such as SOLUSDT.
QUOTE_ASSETS = ("USDT", "USDC", "FDUSD", "BUSD", "TUSD", "USDP", "DAI", "BTC", "ETH", "BNB", "EUR", "TRY", "USD")


class LiveAccountError(RuntimeError):
    pass


class ExchangePort(Protocol):
    def get_account_balance(self, asset: str) -> float: ...

    def get_account_balances(self) -> list[Balance]: ...

    def get_max_borrowable(self, asset: str, symbol: str | None = None) -> Any: ...

    def get_open_orders(self, symbol: Symbol) -> list[Any]: ...

    def cancel_order(self, symbol: Symbol, order_id: str) -> Any: ...

    def cancel_all_open_orders(self, symbol: Symbol) -> Any: ...


@dataclass(frozen=True)
class CapacitySnapshot:
    asset: str
    balance: float
    max_borrowable: float = 0.0
    borrow_limit: float | None = None

    @property
    def operable_capacity(self) -> float:
        return self.balance + self.max_borrowable


def parse_symbol(raw_symbol: str, quote_asset: str = "USDT") -> Symbol | None:
    """Parse an explicit user-entered symbol; never infers an account-wide target."""
    normalized = str(raw_symbol or "").strip().upper().replace("/", "-").replace("_", "-")
    if not normalized:
        return None
    if "-" in normalized:
        symbol = Symbol(normalized)
        return symbol if not symbol.is_empty() else None
    compact = normalized.replace("-", "")
    for quote in (quote_asset, *QUOTE_ASSETS):
        quote = str(quote or "").strip().upper()
        if quote and compact.endswith(quote) and len(compact) > len(quote):
            return Symbol(f"{compact[: -len(quote)]}-{quote}")
    return None


def operable_amount(balances: list[Balance], borrow_asset: str, borrowable_amount: float) -> float:
    """Operable capacity is free balance plus max borrowable; locked funds are not spendable."""
    free_balance = 0.0
    asset = str(borrow_asset or "").upper()
    for balance in balances:
        if str(balance.asset or "").upper() == asset:
            free_balance = float(balance.free or 0.0)
            break
    return free_balance + float(borrowable_amount or 0.0)


def _numeric(payload: Any, key: str) -> float | None:
    value = payload.get(key) if isinstance(payload, dict) else getattr(payload, key, None)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def capacity_snapshot(
    exchange: ExchangePort,
    asset: str,
    *,
    symbol: str | None = None,
    requires_borrow: bool = False,
    borrow_precheck: bool = True,
) -> CapacitySnapshot:
    balance = float(exchange.get_account_balance(asset) or 0.0)
    snapshot = CapacitySnapshot(asset=str(asset).upper(), balance=balance)
    if not requires_borrow or not borrow_precheck:
        return snapshot
    borrow_reader = getattr(exchange, "get_max_borrowable", None)
    if not callable(borrow_reader):
        return snapshot
    payload = borrow_reader(asset, symbol=symbol)
    return CapacitySnapshot(
        asset=snapshot.asset,
        balance=balance,
        max_borrowable=float(_numeric(payload, "amount") or 0.0),
        borrow_limit=_numeric(payload, "borrowLimit"),
    )


def open_order_rows(rows: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        info = row.get("info") if isinstance(row.get("info"), dict) else {}
        order_id = row.get("orderId") or row.get("order_id") or row.get("id") or info.get("orderId") or info.get("order_id")
        items.append(
            {
                "symbol": str(row.get("symbol") or info.get("symbol") or "").replace("/", ""),
                "side": str(row.get("side") or info.get("side") or ""),
                "quantity": float(row.get("origQty") or row.get("amount") or row.get("quantity") or 0.0),
                "order_id": str(order_id or ""),
                "order_type": str(row.get("type") or info.get("type") or ""),
                "price": float(row.get("price") or 0.0),
                "status": str(row.get("status") or info.get("status") or ""),
            }
        )
    return items


class LiveAccountLifecycle:
    def __init__(
        self,
        *,
        base_exchange: Any = None,
        cfg: Any = None,
        log: Any = None,
        credential_repo: Any = None,
        exchange_factory: Any = None,
        cipher: SecretCipher | None = None,
    ):
        self.base_exchange = base_exchange
        self.cfg = cfg
        self.log = log
        self.credential_repo = credential_repo
        self.exchange_factory = exchange_factory
        self.cipher = cipher
        self.exchanges_by_mode: dict[str, Any] = {}

    async def exchange_for_task(self, task_cfg: Any, *, runtime_live_execution_mode: str) -> Any:
        target_mode = MarginMode.CROSS_MARGIN if task_requires_short_capability(task_cfg) else MarginMode.SPOT
        user_id = getattr(task_cfg, "user_id", None)
        if user_id is not None:
            return await self.exchange_for_user(user_id, target_mode)
        if runtime_live_execution_mode != "auto_trade":
            return self.base_exchange
        cached = self.exchanges_by_mode.get(target_mode.value)
        if cached is not None:
            return cached
        try:
            return self.exchange_for_mode(target_mode)
        except Exception as exc:
            if self.log is not None and hasattr(self.log, "warning"):
                self.log.warning(f"failed to create routed exchange for mode={target_mode.value}, falling back to default: {exc}")
            return self.base_exchange

    async def exchange_for_user(self, user_id: int, mode: MarginMode) -> Any:
        repository = self.credential_repo
        if repository is None:
            raise LiveAccountError("live trading requires a user exchange credential store")
        if self.cipher is None:
            raise LiveAccountError("TRADER_SECRET_KEY is required to start user-owned live trading tasks")
        credential = repository.get_default(user_id, "BINANCE")
        if inspect.isawaitable(credential):
            credential = await credential
        context = self.build_credential_context(
            base_cfg=base_exchange_config(self.base_exchange, self.cfg),
            cipher=self.cipher,
            credential=credential,
            user_id=user_id,
            margin_mode=mode,
        )
        return attach_user_exchange_context(self.exchange_factory(context.cfg, self.log), context)

    def exchange_for_mode(self, mode: MarginMode) -> Any:
        cached = self.exchanges_by_mode.get(mode.value)
        if cached is not None:
            return cached
        base_cfg = getattr(self.base_exchange, "cfg", None)
        if base_cfg is None or not hasattr(base_cfg, "with_margin_mode"):
            return self.base_exchange
        routed = self.exchange_factory(base_cfg.with_margin_mode(mode), self.log)
        self.exchanges_by_mode[mode.value] = routed
        return routed

    @staticmethod
    def build_credential_context(
        *,
        base_cfg: ExchangeConfig | None,
        cipher: SecretCipher | None,
        credential: Any,
        user_id: int,
        margin_mode: MarginMode,
    ) -> UserExchangeContext:
        if credential is None:
            raise LiveAccountError(f"missing BINANCE API credential for user_id={user_id}")
        if cipher is None:
            raise LiveAccountError("TRADER_SECRET_KEY is required to read user-owned Binance credentials")
        api_key = cipher.decrypt(credential.encrypted_api_key)
        api_secret = cipher.decrypt(credential.encrypted_api_secret)
        payload = (base_cfg or ExchangeConfig()).to_dict()
        payload["api_key"] = api_key
        payload["api_secret"] = api_secret
        payload["margin_mode"] = margin_mode
        return UserExchangeContext(
            cfg=ExchangeConfig(**payload),
            user_id=user_id,
            credential_id=getattr(credential, "id", None),
            masked_api_key=str(getattr(credential, "masked_api_key", "") or mask_api_key(api_key)),
        )

    @staticmethod
    def default_credential(credentials: list) -> Any:
        for credential in credentials or []:
            if str(getattr(credential, "exchange", "") or "").upper() == "BINANCE":
                return credential
        return None

    @staticmethod
    def preview_open_orders(exchange: ExchangePort, symbol: Symbol) -> list[dict[str, Any]]:
        reader = getattr(exchange, "get_open_orders", None)
        if not callable(reader):
            return []
        return open_order_rows(reader(symbol) or [])

    @staticmethod
    def cancel_open_orders_for_symbol(exchange: ExchangePort, symbol: Symbol, log: Any = None) -> int:
        cancel_all = getattr(exchange, "cancel_all_open_orders", None)
        if not callable(cancel_all):
            return 0
        try:
            cancel_all(symbol)
            return 1
        except Exception as exc:
            if log is not None and hasattr(log, "error"):
                log.error(f"account cancel_all_open_orders failed: symbol={symbol.name()} error={exc}")
            return 0

    async def cancel_task_open_orders(
        self,
        task_id: Any,
        exchange: Any,
        *,
        reason: str,
        fallback_symbols=None,
        records: list | None = None,
        seen: set[tuple[int, str]] | None = None,
        on_canceled: Any = None,
    ) -> bool:
        """ADR-0001 task-scoped cleanup: cancel only orders linked to this 任务."""
        if task_id is None:
            self._cancel_symbols(fallback_symbols or [], exchange, reason=reason, task_id=task_id, seen=seen)
            return False
        records = list(records or [])
        if not records:
            self._cancel_symbols(fallback_symbols or [], exchange, reason=reason, task_id=task_id, seen=seen)
            return False

        fallback_for_incomplete: list[Symbol] = []
        cancel_order = getattr(exchange, "cancel_order", None)
        for record in records:
            symbol = _symbol_from_value(getattr(record, "symbol", None))
            if symbol is None:
                continue
            order_ids = _record_exchange_order_ids(record)
            if not order_ids or not callable(cancel_order):
                fallback_for_incomplete.append(symbol)
                continue
            record_canceled = True
            for order_id in order_ids:
                key = (id(exchange), f"{symbol.name()}:{order_id}")
                if seen is not None:
                    if key in seen:
                        continue
                    seen.add(key)
                try:
                    if self.log is not None and hasattr(self.log, "info"):
                        self.log.info(f"cancel_order: reason={reason} task_id={task_id} symbol={symbol.name()} order_id={order_id}")
                    result = cancel_order(symbol, order_id)
                    if inspect.isawaitable(result):
                        await result
                except Exception as exc:
                    record_canceled = False
                    if self.log is not None and hasattr(self.log, "error"):
                        self.log.error(
                        f"cancel_order failed: reason={reason} task_id={task_id} "
                        f"symbol={symbol.name()} order_id={order_id} error={exc}"
                    )
            if record_canceled and on_canceled is not None:
                callback_result = on_canceled(record)
                if inspect.isawaitable(callback_result):
                    await callback_result

        self._cancel_symbols(fallback_for_incomplete, exchange, reason=reason, task_id=task_id, seen=seen)
        return True

    def _cancel_symbols(self, symbols, exchange, *, reason: str, task_id: Any, seen: set | None) -> None:
        for symbol in symbols or []:
            symbol = _symbol_from_value(symbol)
            if symbol is None:
                continue
            key = (id(exchange), symbol.name())
            if seen is not None:
                if key in seen:
                    continue
                seen.add(key)
            cancel_all = getattr(exchange, "cancel_all_open_orders", None)
            if not callable(cancel_all):
                continue
            try:
                if self.log is not None and hasattr(self.log, "info"):
                    self.log.info(f"cancel_all_open_orders: reason={reason} task_id={task_id} symbol={symbol.name()}")
                cancel_all(symbol)
            except Exception as exc:
                if self.log is not None and hasattr(self.log, "error"):
                    self.log.error(f"cancel_all_open_orders failed: reason={reason} task_id={task_id} symbol={symbol.name()} error={exc}")


def _symbol_from_value(value: Any) -> Symbol | None:
    if value is None:
        return None
    if isinstance(value, Symbol):
        return value if not value.is_empty() else None
    if hasattr(value, "sy"):
        base = str(getattr(value.sy, "base", "") or "").strip().upper()
        quote = str(getattr(value.sy, "quote", "") or "").strip().upper()
        return Symbol(f"{base}-{quote}") if base and quote else None
    return parse_symbol(str(value))


def _record_exchange_order_ids(record: Any) -> list[str]:
    values: list[str] = []
    raw = str(getattr(record, "exchange_order_id", "") or "").strip()
    if raw:
        values.extend(raw.split(","))
    raw_payload = getattr(record, "raw_payload", None)
    if isinstance(raw_payload, dict):
        for key in ("orderId", "order_id", "clientOrderId", "id"):
            value = raw_payload.get(key)
            if value is not None:
                values.append(str(value))
    ret: list[str] = []
    seen: set[str] = set()
    for value in values:
        order_id = str(value or "").strip()
        if order_id and order_id not in seen:
            seen.add(order_id)
            ret.append(order_id)
    return ret
