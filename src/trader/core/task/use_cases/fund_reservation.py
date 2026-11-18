"""Fund reservation preflight, recovery budget restoration, and release use cases."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

from trader.core.execution import ExecutionStatus, resolve_execution_gateway
from trader.core.task.domain import TaskType, task_requires_short_capability
from trader.core.task.exceptions import FundReservationError
from trader.core.task.interfaces import FundReservationStore


def _is_auto_trade_mode(cfg: Any) -> bool:
    mode = str(getattr(cfg, "live_execution_mode", "auto_trade") or "auto_trade").strip().lower()
    try:
        return bool(resolve_execution_gateway(live_execution_mode=mode).can_submit_orders)
    except Exception:
        return False


def _numeric_payload_value(payload: Any, key: str) -> float | None:
    value = payload.get(key) if isinstance(payload, dict) else getattr(payload, key, None)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _execution_record_notional(record: Any) -> float:
    raw_payload = getattr(record, "raw_payload", None)
    if isinstance(raw_payload, dict):
        for key in ("effective_notional", "notional"):
            value = raw_payload.get(key)
            try:
                notional = float(value)
            except (TypeError, ValueError):
                continue
            if notional > 0:
                return notional
    try:
        quantity = float(getattr(record, "quantity", 0.0) or 0.0)
        price = float(getattr(record, "price", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(quantity * price, 0.0)


def reservation_capacity_snapshot(cfg: Any, exchange: Any, asset: str) -> dict[str, float | None]:
    balance_reader = getattr(exchange, "get_account_balance", None)
    if not callable(balance_reader):
        raise FundReservationError(f"cannot read exchange balance for reservation: task_id={getattr(cfg, 'id', None)} asset={asset}")
    balance = float(balance_reader(asset) or 0.0)
    snapshot: dict[str, float | None] = {
        "balance": balance,
        "max_borrowable": 0.0,
        "borrow_limit": None,
        "operable_capacity": balance,
    }
    if not task_requires_short_capability(cfg):
        return snapshot
    if not bool(getattr(cfg, "live_margin_borrow_precheck", True)):
        return snapshot
    borrow_reader = getattr(exchange, "get_max_borrowable", None)
    if not callable(borrow_reader):
        return snapshot
    payload = borrow_reader(asset, symbol=cfg.symbol_interval.symbol())
    borrowable = _numeric_payload_value(payload, "amount")
    snapshot["max_borrowable"] = float(borrowable or 0.0)
    snapshot["borrow_limit"] = _numeric_payload_value(payload, "borrowLimit")
    snapshot["operable_capacity"] = balance + float(snapshot["max_borrowable"] or 0.0)
    return snapshot


def set_task_runtime_budget(cfg: Any, requirement: dict[str, Any], *, remaining: float | None = None) -> None:
    amount = float(requirement["amount"])
    cfg.fund_reservation_account_key = requirement["account_key"]
    cfg.fund_reservation_asset = requirement["asset"]
    cfg.fund_reservation_amount = amount
    cfg.fund_reservation_remaining = amount if remaining is None else max(float(remaining), 0.0)


def format_reservation_rejection_log(cfg: Any, requirement: dict[str, Any], exc: FundReservationError) -> str:
    symbol_interval = getattr(cfg, "symbol_interval", None)
    symbol = symbol_interval.symbol() if symbol_interval is not None else ""
    strategy = cfg.strategy_name() if callable(getattr(cfg, "strategy_name", None)) else ""
    return (
        "strategy rejected before execution: "
        "rule=requested <= operable_capacity "
        f"task_id={getattr(cfg, 'id', None)} "
        f"symbol={symbol} "
        f"strategy={strategy} "
        f"live_execution_mode={getattr(cfg, 'live_execution_mode', None)} "
        f"account_key={requirement.get('account_key')} "
        f"market_mode={requirement.get('market_mode')} "
        f"asset={requirement.get('asset')} "
        f"required={requirement.get('amount')} "
        f"balance={requirement.get('balance')} "
        f"max_borrowable={requirement.get('max_borrowable')} "
        f"borrow_limit={requirement.get('borrow_limit')} "
        f"operable_capacity={requirement.get('operable_capacity')} "
        f"reason={exc}"
    )


class PreflightLiveTaskFunds:
    """Validate operable account capacity and populate runtime fund budgets before live tasks start."""

    def __init__(
        self,
        *,
        exchange_resolver: Callable[[Any], Any],
        account_key_resolver: Callable[[Any], Any],
        credential_id_resolver: Callable[[Any], Any] | None = None,
        default_cash: float = 0.0,
        log: Any = None,
    ):
        self.exchange_resolver = exchange_resolver
        self.account_key_resolver = account_key_resolver
        self.credential_id_resolver = credential_id_resolver
        self.default_cash = float(default_cash)
        self.log = log

    async def build_requirement(self, cfg: Any) -> dict[str, Any] | None:
        if getattr(cfg, "ttype", None) != TaskType.TRADER:
            return None
        if not _is_auto_trade_mode(cfg):
            return None
        if getattr(cfg, "symbol_interval", None) is None:
            return None
        amount = self._reservation_amount(cfg)
        if amount <= 0:
            return None
        exchange = self.exchange_resolver(cfg)
        if inspect.isawaitable(exchange):
            exchange = await exchange
        asset = str(cfg.symbol_interval.sy.quote).upper()
        snapshot = await asyncio.to_thread(reservation_capacity_snapshot, cfg, exchange, asset)
        account_key = self.account_key_resolver(cfg)
        if inspect.isawaitable(account_key):
            account_key = await account_key
        credential_id = None
        if self.credential_id_resolver is not None:
            credential_id = self.credential_id_resolver(cfg)
            if inspect.isawaitable(credential_id):
                credential_id = await credential_id
        exchange_name = exchange.name() if callable(getattr(exchange, "name", None)) else "BINANCE"
        return {
            "account_key": account_key,
            "exchange": exchange_name,
            "credential_id": credential_id,
            "user_id": getattr(cfg, "user_id", None),
            "task_id": int(cfg.id),
            "asset": asset,
            "amount": amount,
            "capacity": float(snapshot["operable_capacity"] or 0.0),
            "market_mode": getattr(getattr(exchange, "margin_mode", None), "value", None),
            "balance": snapshot["balance"],
            "max_borrowable": snapshot["max_borrowable"],
            "borrow_limit": snapshot["borrow_limit"],
            "operable_capacity": snapshot["operable_capacity"],
            "reason": "live_task_start",
        }

    async def execute(self, taskcs: list[Any]) -> None:
        for cfg in taskcs:
            requirement = await self.build_requirement(cfg)
            if requirement is None:
                continue
            amount = float(requirement["amount"])
            capacity = float(requirement["capacity"])
            if amount > capacity + 1e-12:
                exc = FundReservationError(
                    "insufficient live task balance: "
                    f"task_id={getattr(cfg, 'id', None)} "
                    f"account_key={requirement.get('account_key')} "
                    f"asset={requirement.get('asset')} "
                    f"capacity={capacity} "
                    f"balance={requirement.get('balance')} "
                    f"max_borrowable={requirement.get('max_borrowable')} "
                    f"borrow_limit={requirement.get('borrow_limit')} "
                    f"operable_capacity={requirement.get('operable_capacity')} "
                    f"requested={amount}"
                )
                if self.log is not None and hasattr(self.log, "error"):
                    self.log.error(format_reservation_rejection_log(cfg, requirement, exc))
                raise exc
            set_task_runtime_budget(cfg, requirement)

    def _reservation_amount(self, cfg: Any) -> float:
        max_notional = float(getattr(cfg, "live_trade_max_notional", 0.0) or 0.0)
        if max_notional > 0:
            return max_notional
        if getattr(cfg, "free", -1) >= 0:
            return float(cfg.free)
        return self.default_cash


class RestoreRecoveredTaskBudget:
    """Reconstruct runtime remaining budget for a recovered task without fresh balance rejection."""

    def __init__(
        self,
        *,
        execution_state_store: Any = None,
        exchange_resolver: Callable[[Any], Any],
        account_key_resolver: Callable[[Any], Any],
        credential_id_resolver: Callable[[Any], Any] | None = None,
        default_cash: float = 0.0,
    ):
        self.execution_state_store = execution_state_store
        self.preflight = PreflightLiveTaskFunds(
            exchange_resolver=exchange_resolver,
            account_key_resolver=account_key_resolver,
            credential_id_resolver=credential_id_resolver,
            default_cash=default_cash,
        )

    async def execute(self, cfg: Any) -> None:
        requirement = await self.preflight.build_requirement(cfg)
        if requirement is None:
            return
        amount = float(requirement["amount"])
        spent = await self._submitted_entry_notional(int(cfg.id))
        set_task_runtime_budget(cfg, requirement, remaining=max(amount - spent, 0.0))

    async def _submitted_entry_notional(self, task_id: int) -> float:
        list_open_by_task = getattr(self.execution_state_store, "list_open_by_task", None)
        if not callable(list_open_by_task):
            return 0.0
        records = list_open_by_task(task_id)
        if inspect.isawaitable(records):
            records = await records
        total = 0.0
        for record in records or []:
            if str(getattr(record, "order_role", "")).lower() != "entry":
                continue
            status = getattr(record, "status", None)
            status_value = getattr(status, "value", status)
            if status_value != ExecutionStatus.SUBMITTED.value:
                continue
            notional = _execution_record_notional(record)
            if notional > 0:
                total += notional
        return total


class ReleaseTaskFunds:
    """Release an active task's fund reservation without propagating store errors."""

    def __init__(self, store: FundReservationStore | None, *, log: Any = None):
        self.store = store
        self.log = log

    async def execute(self, task_id: int, *, reason: str) -> None:
        if self.store is None:
            return
        try:
            await self.store.release_task(task_id, reason=reason)
        except Exception as exc:
            if self.log is not None and hasattr(self.log, "error"):
                self.log.error(f"Failed to release task fund reservation: task_id={task_id} reason={reason} error={exc}")
