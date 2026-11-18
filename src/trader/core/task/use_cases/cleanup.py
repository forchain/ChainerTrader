"""Task-scoped open-order cleanup use cases (ADR-0001)."""

from __future__ import annotations

import inspect
from datetime import datetime
from typing import Any

from trader.core.execution import ExecutionStatus
from trader.core.shared.domain import Symbol
from trader.core.task.domain import TaskType

KNOWN_QUOTES = ("FDUSD", "USDT", "USDC", "BUSD", "TUSD", "USDP", "DAI", "BTC", "ETH", "BNB", "EUR", "TRY", "USD")


def symbol_from_value(value: Any) -> Symbol | None:
    if isinstance(value, Symbol):
        return value
    sy = getattr(value, "sy", None)
    if isinstance(sy, Symbol):
        return sy
    text = str(value or "").strip().upper()
    if not text:
        return None
    text = text.replace("/", "-").replace("_", "-")
    if "-" in text:
        return Symbol(text)
    for quote in KNOWN_QUOTES:
        if text.endswith(quote) and len(text) > len(quote):
            return Symbol(f"{text[:-len(quote)]}-{quote}")
    return None


def dedupe_symbols(symbols) -> list[Symbol]:
    ret: list[Symbol] = []
    seen: set[str] = set()
    for symbol in symbols or []:
        if symbol is None:
            continue
        normalized = symbol_from_value(symbol)
        if normalized is None or normalized.is_empty():
            continue
        name = normalized.name()
        if name in seen:
            continue
        seen.add(name)
        ret.append(normalized)
    return ret


def record_exchange_order_ids(record: Any) -> list[str]:
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
        if not order_id or order_id in seen:
            continue
        seen.add(order_id)
        ret.append(order_id)
    return ret


def same_cleanup_account(cfg: Any, task: Any) -> bool:
    running_cfg = getattr(task, "tcfg", None)
    cfg_user_id = getattr(cfg, "user_id", None)
    running_user_id = getattr(running_cfg, "user_id", None)
    if cfg_user_id is not None or running_user_id is not None:
        return cfg_user_id == running_user_id
    return True


def task_is_running(task: Any) -> bool:
    state = getattr(task, "ts", None)
    is_running = getattr(state, "is_running", None)
    if callable(is_running):
        return bool(is_running())
    return True


class CancelTaskOpenOrders:
    """Cancel only open orders belonging to a specific task (ADR-0001)."""

    def __init__(self, *, execution_state_store: Any = None, log: Any = None):
        self.execution_state_store = execution_state_store
        self.log = log

    async def execute(
        self,
        task_id: int | None,
        exchange: Any,
        *,
        reason: str,
        fallback_symbols=None,
        seen: set[tuple[int, str]] | None = None,
    ) -> bool:
        if task_id is None:
            self.cancel_for_symbols(fallback_symbols or [], exchange, reason=reason, task_id=task_id, seen=seen)
            return False

        records = await self._open_records_for_task(int(task_id))
        if not records:
            self.cancel_for_symbols(fallback_symbols or [], exchange, reason=reason, task_id=task_id, seen=seen)
            return False

        fallback_for_incomplete_records: list[Symbol] = []
        cancel_order = getattr(exchange, "cancel_order", None)
        for record in records:
            symbol = symbol_from_value(getattr(record, "symbol", None))
            if symbol is None:
                continue
            order_ids = record_exchange_order_ids(record)
            if not order_ids or not callable(cancel_order):
                fallback_for_incomplete_records.append(symbol)
                continue
            for order_id in order_ids:
                key = (id(exchange), f"{symbol.name()}:{order_id}")
                if seen is not None:
                    if key in seen:
                        continue
                    seen.add(key)
                try:
                    self._log_info(f"cancel_order: reason={reason} task_id={task_id} symbol={symbol.name()} order_id={order_id}")
                    result = cancel_order(symbol, order_id)
                    if inspect.isawaitable(result):
                        await result
                    await self._mark_canceled(record)
                except Exception as exc:
                    self._log_error(
                        f"cancel_order failed: reason={reason} task_id={task_id} symbol={symbol.name()} order_id={order_id} error={exc}"
                    )

        self.cancel_for_symbols(
            fallback_for_incomplete_records,
            exchange,
            reason=reason,
            task_id=task_id,
            seen=seen,
        )
        return True

    def cancel_for_symbols(
        self,
        symbols,
        exchange: Any,
        *,
        reason: str,
        task_id: int | None = None,
        seen: set[tuple[int, str]] | None = None,
    ) -> None:
        cancel = getattr(exchange, "cancel_all_open_orders", None)
        if not callable(cancel):
            return
        for symbol in dedupe_symbols(symbols):
            symbol_name = symbol.name()
            if not symbol_name:
                continue
            key = (id(exchange), symbol_name)
            if seen is not None:
                if key in seen:
                    continue
                seen.add(key)
            try:
                self._log_info(f"cancel_all_open_orders: reason={reason} task_id={task_id} symbol={symbol_name}")
                cancel(symbol)
            except Exception as exc:
                self._log_error(
                    f"cancel_all_open_orders failed: reason={reason} task_id={task_id} symbol={symbol_name} error={exc}"
                )

    async def _open_records_for_task(self, task_id: int) -> list[Any]:
        list_open_by_task = getattr(self.execution_state_store, "list_open_by_task", None)
        if not callable(list_open_by_task):
            return []
        records = list_open_by_task(task_id)
        if inspect.isawaitable(records):
            records = await records
        return list(records or [])

    async def _mark_canceled(self, record: Any) -> None:
        save = getattr(self.execution_state_store, "save", None)
        if not callable(save) or not hasattr(record, "with_updates"):
            return
        updated = record.with_updates(status=ExecutionStatus.CANCELED, updated_at=int(datetime.now().timestamp()))
        result = save(updated)
        if inspect.isawaitable(result):
            await result

    def _log_info(self, message: str) -> None:
        if self.log is not None and hasattr(self.log, "info"):
            self.log.info(message)

    def _log_error(self, message: str) -> None:
        if self.log is not None and hasattr(self.log, "error"):
            self.log.error(message)


class CleanupRunningTasksBeforeStart:
    """Clean up open orders for currently running same-account tasks before starting a new task."""

    def __init__(self, *, execution_state_store: Any = None, log: Any = None):
        self.cancel_use_case = CancelTaskOpenOrders(execution_state_store=execution_state_store, log=log)

    async def execute(
        self,
        cfg: Any,
        running_tasks: list[Any],
        *,
        default_exchange: Any,
        reason: str = "task_start",
        seen: set[tuple[int, str]] | None = None,
    ) -> None:
        for task in running_tasks:
            if not task_is_running(task):
                continue
            if not same_cleanup_account(cfg, task):
                continue
            si = getattr(getattr(task, "tcfg", None), "symbol_interval", None)
            task_exchange = getattr(task, "exchange", None) or default_exchange
            await self.cancel_use_case.execute(
                getattr(getattr(task, "tcfg", None), "id", None),
                task_exchange,
                reason=reason,
                fallback_symbols=[si.sy] if si is not None else [],
                seen=seen,
            )

    async def execute_batch(
        self,
        taskcs: list[Any],
        running_tasks: list[Any],
        *,
        exchange_resolver,
    ) -> None:
        seen: set[tuple[int, str]] = set()
        for cfg in taskcs:
            if getattr(cfg, "ttype", None) != TaskType.TRADER:
                continue
            task_exchange = exchange_resolver(cfg)
            if inspect.isawaitable(task_exchange):
                task_exchange = await task_exchange
            await self.execute(cfg, running_tasks, default_exchange=task_exchange, reason="task_start", seen=seen)
