"""Tests for order lifecycle management in TaskManager.

Rules:
- One live task per account at any time.
- add_task   → cancel currently-running task orders for the same account before live balance preflight.
- recover_task → do NOT cancel anything (orders belong to the recovering task).
- close_task_state → cancel the closing task's persisted open execution orders.
- All cancellation is best-effort (errors are logged, never raised).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from trader.common.config import Config
from trader.execution.models import ExecutionStatus, GatewayMode
from trader.execution.state import ExecutionStateRecord
from trader.task.task_manager import TaskManager
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import Interval, Symbol, SymbolInterval


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _si(symbol: str = "BTC-USDT") -> SymbolInterval:
    return SymbolInterval(symbol, Interval.INTERVAL_1h)


def _cfg(task_id: int = 1, strategy: str = "TestStrategy", symbol: str = "BTC-USDT", user_id=None) -> SimpleNamespace:
    si = _si(symbol)
    cfg = SimpleNamespace(
        id=task_id,
        ttype=TaskType.TRADER,
        symbol_interval=si,
        strategies=[strategy],
        user_id=user_id,
        free=-1,
    )
    cfg.strategy_name = lambda: strategy  # type: ignore[attr-defined]
    return cfg


class _FakeExchange:
    def __init__(self):
        self.cancel_all_open_orders_calls: list[str] = []
        self.cancel_order_calls: list[tuple[str, str]] = []
        self.bind_order_context_calls: list = []

    def cancel_all_open_orders(self, symbol: Symbol):
        self.cancel_all_open_orders_calls.append(symbol.name())

    def cancel_order(self, symbol: Symbol, order_id: str):
        self.cancel_order_calls.append((symbol.name(), order_id))
        return {"id": order_id, "status": "canceled"}

    def bind_order_context(self, task_id=None, strategy_name=None):
        self.bind_order_context_calls.append({"task_id": task_id, "strategy_name": strategy_name})


class _FakeTask:
    def __init__(self, cfg, exchange):
        self.tcfg = cfg
        self.exchange = exchange
        self.ts = SimpleNamespace(
            id=cfg.id,
            user_id=cfg.user_id,
            state="RUNNING",
            is_running=lambda: True,
        )
        self._stopped = False

    def id(self):
        return self.tcfg.id

    def stop(self):
        self._stopped = True

    async def start(self, queue):
        pass


def _manager() -> TaskManager:
    log = MagicMock()
    db = MagicMock()
    return TaskManager(cfg=Config(), log=log, db_manager=db, exchange=MagicMock())


def _execution_record(task_id: int, *, symbol: str = "BTCUSDT", order_id: str = "order-1") -> ExecutionStateRecord:
    return ExecutionStateRecord(
        task_id=task_id,
        idempotency_key=f"key-{task_id}-{order_id}",
        intent_id=f"intent-{task_id}",
        operation_id=f"op-{task_id}",
        gateway=GatewayMode.BINANCE_LIVE,
        staged_execution_mode="auto_trade",
        symbol=symbol,
        order_role="entry",
        status=ExecutionStatus.SUBMITTED,
        exchange_order_id=order_id,
    )


class _ExecutionStore:
    def __init__(self, records_by_task: dict[int, list[ExecutionStateRecord]]):
        self.records_by_task = records_by_task
        self.saved: list[ExecutionStateRecord] = []

    async def list_open_by_task(self, task_id: int):
        return list(self.records_by_task.get(task_id, []))

    async def save(self, record):
        self.saved.append(record)
        return record


# ---------------------------------------------------------------------------
# add_task – cancels symbol-scoped open orders
# ---------------------------------------------------------------------------


def test_add_task_does_not_cancel_configured_cleanup_symbols_without_running_tasks():
    manager = TaskManager(
        cfg=Config(live_order_cleanup_symbols=["SOL-USDT", "BNBUSDT"]),
        log=MagicMock(),
        db_manager=MagicMock(),
        exchange=MagicMock(),
    )
    exchange = _FakeExchange()
    task_cfg = _cfg(task_id=10)
    fake_task = _FakeTask(task_cfg, exchange)

    async def _run():
        with (
            patch.object(manager, "_exchange_for_task", AsyncMock(return_value=exchange)),
            patch.object(manager, "_build_task", return_value=fake_task),
        ):
            await manager.add_task(task_cfg, asyncio.Queue())

    asyncio.run(_run())

    assert exchange.cancel_all_open_orders_calls == []
    assert exchange.cancel_order_calls == []


def test_add_task_skips_cleanup_when_no_configured_symbols_and_no_running_tasks():
    manager = _manager()
    exchange = _FakeExchange()
    task_cfg = _cfg(task_id=10)
    fake_task = _FakeTask(task_cfg, exchange)

    async def _run():
        with (
            patch.object(manager, "_exchange_for_task", AsyncMock(return_value=exchange)),
            patch.object(manager, "_build_task", return_value=fake_task),
        ):
            await manager.add_task(task_cfg, asyncio.Queue())

    asyncio.run(_run())

    assert exchange.cancel_all_open_orders_calls == []


def test_do_add_tasks_cancels_running_task_orders_before_balance_preflight():
    manager = TaskManager(
        cfg=Config(live_order_cleanup_symbols=["SOL-USDT", "BNBUSDT"]),
        log=MagicMock(),
        db_manager=MagicMock(),
        exchange=MagicMock(),
    )
    exchange = _FakeExchange()
    running_exchange = exchange
    running_cfg = _cfg(task_id=5, symbol="ETH-USDT")
    manager.tasks[running_cfg.id] = _FakeTask(running_cfg, running_exchange)
    task_cfg = _cfg(task_id=10, symbol="BTC-USDT")
    fake_task = _FakeTask(task_cfg, exchange)
    manager.db_manager.execution_state = _ExecutionStore({5: [_execution_record(5, symbol="ETHUSDT", order_id="live-5")]})
    events = []

    def _cancel_order(symbol: Symbol, order_id: str):
        exchange.cancel_order_calls.append((symbol.name(), order_id))
        events.append(f"cancel:{symbol.name()}:{order_id}")

    async def _start(_queue):
        events.append("start_task")

    async def _preflight_balances(_taskcs):
        events.append("preflight_balances")

    exchange.cancel_order = _cancel_order
    fake_task.start = _start

    async def _run():
        with (
            patch.object(manager, "_ensure_routed_exchanges", AsyncMock()),
            patch.object(manager, "_preflight_live_task_balances", _preflight_balances),
            patch.object(manager, "_exchange_for_task", AsyncMock(return_value=exchange)),
            patch.object(manager, "_build_task", return_value=fake_task),
            patch.object(manager, "_persist_task_states", AsyncMock()),
            patch.object(manager, "_release_task_funds", AsyncMock()),
        ):
            await manager.do_add_tasks([task_cfg], asyncio.Queue())

    asyncio.run(_run())

    assert events == ["cancel:ETHUSDT:live-5", "preflight_balances", "start_task"]
    assert exchange.cancel_all_open_orders_calls == []
    assert exchange.cancel_order_calls == [("ETHUSDT", "live-5")]


def test_add_task_binds_order_context():
    manager = _manager()
    exchange = _FakeExchange()
    task_cfg = _cfg(task_id=42, strategy="ShihunRSI")
    fake_task = _FakeTask(task_cfg, exchange)

    async def _run():
        with (
            patch.object(manager, "_exchange_for_task", AsyncMock(return_value=exchange)),
            patch.object(manager, "_build_task", return_value=fake_task),
        ):
            await manager.add_task(task_cfg, asyncio.Queue())

    asyncio.run(_run())

    assert len(exchange.bind_order_context_calls) == 1
    ctx = exchange.bind_order_context_calls[0]
    assert ctx["task_id"] == 42
    assert ctx["strategy_name"] == "ShihunRSI"


# ---------------------------------------------------------------------------
# recover_task – does NOT cancel any orders
# ---------------------------------------------------------------------------


def test_recover_task_does_not_cancel_any_orders():
    manager = _manager()
    exchange = _FakeExchange()
    task_cfg = _cfg(task_id=5)
    fake_task = _FakeTask(task_cfg, exchange)

    async def _run():
        with (
            patch.object(manager, "_restore_recovered_task_runtime_budget", AsyncMock()),
            patch.object(manager, "_exchange_for_task", AsyncMock(return_value=exchange)),
            patch.object(manager, "_build_task", return_value=fake_task),
        ):
            await manager.recover_task(task_cfg, asyncio.Queue())

    asyncio.run(_run())

    assert exchange.cancel_all_open_orders_calls == []


def test_recover_task_still_binds_order_context():
    manager = _manager()
    exchange = _FakeExchange()
    task_cfg = _cfg(task_id=5, strategy="Grid")
    fake_task = _FakeTask(task_cfg, exchange)

    async def _run():
        with (
            patch.object(manager, "_restore_recovered_task_runtime_budget", AsyncMock()),
            patch.object(manager, "_exchange_for_task", AsyncMock(return_value=exchange)),
            patch.object(manager, "_build_task", return_value=fake_task),
        ):
            await manager.recover_task(task_cfg, asyncio.Queue())

    asyncio.run(_run())

    assert len(exchange.bind_order_context_calls) == 1
    assert exchange.bind_order_context_calls[0]["task_id"] == 5


# ---------------------------------------------------------------------------
# close_task_state – cancels task-scoped open orders
# ---------------------------------------------------------------------------


def test_close_task_state_cancels_task_execution_orders():
    manager = TaskManager(
        cfg=Config(live_order_cleanup_symbols=["SOL-USDT"]),
        log=MagicMock(),
        db_manager=MagicMock(),
        exchange=MagicMock(),
    )
    manager.db_manager.execution_state = _ExecutionStore({7: [_execution_record(7, symbol="ETHUSDT", order_id="live-7")]})
    exchange = _FakeExchange()
    task_cfg = _cfg(task_id=7, symbol="ETH-USDT")
    fake_task = _FakeTask(task_cfg, exchange)
    manager.tasks[task_cfg.id] = fake_task

    async def _run():
        with patch.object(manager, "_persist_task_states", AsyncMock()):
            with patch.object(manager, "_release_task_funds", AsyncMock()):
                return await manager.close_task_state(task_cfg.id)

    result = asyncio.run(_run())

    assert result is True
    assert fake_task._stopped
    assert exchange.cancel_order_calls == [("ETHUSDT", "live-7")]
    assert exchange.cancel_all_open_orders_calls == []


def test_close_task_state_falls_back_to_task_symbol_when_no_execution_records():
    manager = TaskManager(
        cfg=Config(live_order_cleanup_symbols=["SOL-USDT"]),
        log=MagicMock(),
        db_manager=MagicMock(),
        exchange=MagicMock(),
    )
    manager.db_manager.execution_state = _ExecutionStore({})
    exchange = _FakeExchange()
    task_cfg = _cfg(task_id=7, symbol="ETH-USDT")
    fake_task = _FakeTask(task_cfg, exchange)
    manager.tasks[task_cfg.id] = fake_task

    async def _run():
        with patch.object(manager, "_persist_task_states", AsyncMock()):
            with patch.object(manager, "_release_task_funds", AsyncMock()):
                return await manager.close_task_state(task_cfg.id)

    result = asyncio.run(_run())

    assert result is True
    assert exchange.cancel_order_calls == []
    assert exchange.cancel_all_open_orders_calls == ["ETHUSDT"]


def test_close_persisted_running_task_cancels_task_execution_orders():
    manager = TaskManager(
        cfg=Config(),
        log=MagicMock(),
        db_manager=MagicMock(),
        exchange=MagicMock(),
    )
    manager.db_manager.execution_state = _ExecutionStore({7: [_execution_record(7, symbol="ETHUSDT", order_id="live-7")]})
    state = SimpleNamespace(
        id=7,
        is_running=lambda: True,
        config_json='[{"id":7,"task_type":"TRADER","symbol":"ETH-USDT","interval":"1h","strategies":"TestStrategy"}]',
        state=None,
    )
    manager.db_manager.task.get_task = AsyncMock(return_value=state)
    exchange = _FakeExchange()

    async def _run():
        with (
            patch.object(manager, "get_task", return_value=None),
            patch.object(manager, "_exchange_for_task", AsyncMock(return_value=exchange)),
            patch.object(manager, "_persist_task_states", AsyncMock()),
            patch.object(manager, "_release_task_funds", AsyncMock()),
        ):
            return await manager.close_task_state(7)

    result = asyncio.run(_run())

    assert result is True
    assert exchange.cancel_order_calls == [("ETHUSDT", "live-7")]
    assert exchange.cancel_all_open_orders_calls == []


# ---------------------------------------------------------------------------
# Error handling – best-effort (errors logged, never raised)
# ---------------------------------------------------------------------------


def test_cancel_all_open_orders_does_not_propagate_errors():
    manager = _manager()

    class FailingExchange(_FakeExchange):
        def cancel_all_open_orders(self, symbol):
            super().cancel_all_open_orders(symbol)
            raise RuntimeError("network timeout")

    task_cfg = _cfg(task_id=99)
    # Must not raise
    manager._cancel_open_orders_for_symbols([task_cfg.symbol_interval.sy], FailingExchange(), reason="test", task_id=task_cfg.id)


# ---------------------------------------------------------------------------
# _bind_order_context falls through to nested ccxt_driver
# ---------------------------------------------------------------------------


def test_bind_order_context_falls_through_to_nested_ccxt_driver():
    manager = _manager()
    task_cfg = _cfg(task_id=7, strategy="Breakout")

    bind_calls = []

    class FakeCcxtDriver:
        def bind_order_context(self, task_id=None, strategy_name=None):
            bind_calls.append({"task_id": task_id, "strategy_name": strategy_name})

    class ExchangeWithoutBind:
        ccxt_driver = FakeCcxtDriver()

    manager._bind_order_context(task_cfg, ExchangeWithoutBind())

    assert bind_calls == [{"task_id": 7, "strategy_name": "Breakout"}]
