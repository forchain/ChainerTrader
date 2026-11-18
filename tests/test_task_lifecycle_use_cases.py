from __future__ import annotations

import ast
import json
from datetime import datetime
from pathlib import Path

import pytest

from tests.persistence_harness import InMemoryTaskRepository
from trader.adapters.outbound.persistence.account_fund_reservation import AccountFundReservationCol
from trader.core.execution import ExecutionStateRecord, ExecutionStatus, GatewayMode
from trader.core.shared.domain import Interval, Symbol, SymbolInterval
from trader.core.task import (
    FundReservationError,
    FundReservationStore,
    TaskConfig,
    TaskEventPublisher,
    TaskRunner,
    TaskState,
    TaskStateType,
    TaskType,
)
from trader.core.task.use_cases import (
    CancelTaskOpenOrders,
    CleanupRunningTasksBeforeStart,
    PlanStartupTasks,
    PreflightLiveTaskFunds,
    RecoverRunningTasks,
    ReleaseTaskFunds,
    RestoreRecoveredTaskBudget,
    StopTask,
    StopUserRunningTasks,
    SubmitTasks,
)
from trader.live import monitor as live_monitor
from trader.live.monitor import LiveEventBus


class _FakeReservationStore(FundReservationStore):
    def __init__(self):
        self.active: dict[int, dict] = {}
        self.released: list[tuple[int, str]] = []

    async def reserve(self, *, account_key, exchange, credential_id, user_id, task_id, asset, amount, capacity, reason, **_kwargs):
        self.active[int(task_id)] = {
            "account_key": account_key,
            "asset": asset,
            "amount": amount,
            "capacity": capacity,
            "reason": reason,
        }
        return self.active[int(task_id)]

    async def active_reserved_amount(self, account_key: str, asset: str) -> float:
        return sum(item["amount"] for item in self.active.values() if item["account_key"] == account_key and item["asset"] == asset)

    async def remaining_for_task(self, task_id: int, asset: str) -> float | None:
        item = self.active.get(int(task_id))
        return item["amount"] if item and item["asset"] == asset else None

    async def mark_spent(self, task_id: int, asset: str, amount: float):
        return self.active.get(int(task_id))

    async def release_task(self, task_id: int, *, reason: str) -> int:
        self.released.append((int(task_id), reason))
        return 1 if self.active.pop(int(task_id), None) is not None else 0

    async def get_active_for_task(self, task_id: int, asset: str):
        item = self.active.get(int(task_id))
        return item if item and item["asset"] == asset else None

    async def release_inactive_tasks(self, running_task_ids: set[int], *, reason: str) -> int:
        inactive = [tid for tid in list(self.active) if tid not in running_task_ids]
        for tid in inactive:
            await self.release_task(tid, reason=reason)
        return len(inactive)


class _FakeExecutionStateStore:
    def __init__(self, records: list[ExecutionStateRecord] | None = None):
        self.records = list(records or [])
        self.saved: list[ExecutionStateRecord] = []

    async def list_open_by_task(self, task_id: int) -> list[ExecutionStateRecord]:
        return [r for r in self.records if r.task_id == task_id and r.status != ExecutionStatus.CANCELED]

    async def save(self, record: ExecutionStateRecord) -> None:
        self.saved.append(record)
        for idx, existing in enumerate(self.records):
            if existing.idempotency_key == record.idempotency_key:
                self.records[idx] = record
                break


class _FakeExchange:
    def __init__(self, balances: dict[str, float] | None = None, borrowables: dict[str, float] | None = None):
        self.balances = dict(balances or {"USDT": 1000.0})
        self.borrowables = dict(borrowables or {})
        self.canceled_orders: list[tuple[str, str]] = []
        self.canceled_symbols: list[str] = []
        self.margin_mode = type("Mode", (), {"value": "spot"})()

    def name(self) -> str:
        return "BINANCE"

    def get_account_balance(self, asset: str) -> float:
        return float(self.balances.get(asset.upper(), 0.0))

    def get_max_borrowable(self, asset: str, symbol: str | None = None) -> dict:
        return {"amount": float(self.borrowables.get(asset.upper(), 0.0)), "borrowLimit": 5000.0}

    def cancel_order(self, symbol: Symbol, order_id: str) -> dict:
        self.canceled_orders.append((symbol.name(), str(order_id)))
        return {"orderId": order_id, "status": "CANCELED"}

    def cancel_all_open_orders(self, symbol: Symbol) -> list:
        self.canceled_symbols.append(symbol.name())
        return []


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _make_state(task_id: int, name: str, *, state: TaskStateType, config_json: str, user_id: int) -> TaskState:
    ts = TaskState(task_id, name, datetime.now(), config_json=config_json, user_id=user_id)
    ts.state = state
    return ts


class _FakeTaskRunner(TaskRunner):
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.started: list[int] = []

    async def run(self, cfg: TaskConfig, **kwargs) -> TaskState:
        self.started.append(cfg.id)
        if self.fail:
            raise RuntimeError(f"boom-{cfg.id}")
        return _make_state(
            cfg.id,
            f"{cfg.id}.{cfg.ttype.name}.{cfg.symbol_interval.name()}",
            state=TaskStateType.DONE,
            config_json="[]",
            user_id=cfg.user_id,
        )


def _live_cfg(
    task_id: int,
    *,
    user_id: int = 7,
    symbol: str = "BTC-USDT",
    max_notional: float = 100.0,
    chainer_mode: str = "LONG_ONLY",
) -> TaskConfig:
    return TaskConfig(
        task_id,
        TaskType.TRADER,
        SymbolInterval(symbol, Interval("1m")),
        strategies=["macd_triple_divergence"],
        free=max_notional,
        live_execution_mode="auto_trade",
        live_trade_max_notional=max_notional,
        strategy_params={"chainer_mode": chainer_mode},
        user_id=user_id,
    )


def _exec_record(
    *,
    task_id: int,
    key: str,
    symbol: str = "BTCUSDT",
    order_id: str = "ord-1",
    role: str = "entry",
    notional: float = 40.0,
) -> ExecutionStateRecord:
    return ExecutionStateRecord(
        idempotency_key=key,
        intent_id=f"intent-{key}",
        operation_id=f"op-{key}",
        gateway=GatewayMode.BINANCE_LIVE,
        staged_execution_mode="auto_trade",
        symbol=symbol,
        order_role=role,
        status=ExecutionStatus.SUBMITTED,
        task_id=task_id,
        exchange_order_id=order_id,
        quantity=0.001,
        price=notional / 0.001,
        raw_payload={"effective_notional": notional},
    )


def test_ports_and_event_bus_have_no_global_singleton():
    assert not hasattr(live_monitor, "GLOBAL_LIVE_EVENT_BUS")
    assert isinstance(LiveEventBus(), TaskEventPublisher)
    assert issubclass(AccountFundReservationCol, FundReservationStore)


def test_no_asyncio_run_in_task_lifecycle_modules():
    root = Path(__file__).resolve().parents[1] / "src" / "trader"
    for rel in ("task/base_task.py", "task/task_manager.py"):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "run" and isinstance(node.value, ast.Name) and node.value.id == "asyncio":
                pytest.fail(f"asyncio.run found in {rel}")
    for path in (root / "core" / "task").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "run" and isinstance(node.value, ast.Name) and node.value.id == "asyncio":
                pytest.fail(f"asyncio.run found in {path}")


@pytest.mark.anyio
async def test_adr0001_cancel_task_open_orders_cancels_only_task_records_without_real_app():
    store = _FakeExecutionStateStore(
        [
            _exec_record(task_id=10, key="k1", symbol="BTCUSDT", order_id="o-10-a"),
            _exec_record(task_id=10, key="k2", symbol="BTCUSDT", order_id="o-10-b"),
            _exec_record(task_id=99, key="k3", symbol="ETHUSDT", order_id="o-99-a"),
        ]
    )
    exchange = _FakeExchange()

    used_records = await CancelTaskOpenOrders(execution_state_store=store).execute(
        10,
        exchange,
        reason="task_closed",
        fallback_symbols=[Symbol("BTC-USDT")],
    )

    assert used_records is True
    assert exchange.canceled_orders == [("BTCUSDT", "o-10-a"), ("BTCUSDT", "o-10-b")]
    assert exchange.canceled_symbols == []
    assert all(r.status == ExecutionStatus.CANCELED for r in store.records if r.task_id == 10)
    assert store.records[2].status == ExecutionStatus.SUBMITTED


@pytest.mark.anyio
async def test_adr0001_cleanup_running_tasks_before_start_is_account_scoped():
    exchange = _FakeExchange()
    store = _FakeExecutionStateStore([_exec_record(task_id=1, key="k1", symbol="BTCUSDT", order_id="o-1")])
    cfg_user_1 = _live_cfg(2, user_id=1)
    running_user_1 = type(
        "T",
        (),
        {"tcfg": _live_cfg(1, user_id=1), "ts": type("TS", (), {"is_running": lambda self: True})(), "exchange": exchange},
    )()
    running_user_2 = type(
        "T",
        (),
        {"tcfg": _live_cfg(3, user_id=2, symbol="ETH-USDT"), "ts": type("TS", (), {"is_running": lambda self: True})(), "exchange": exchange},
    )()

    await CleanupRunningTasksBeforeStart(execution_state_store=store).execute(
        cfg_user_1,
        [running_user_1, running_user_2],
        default_exchange=exchange,
        reason="task_start",
    )

    assert exchange.canceled_orders == [("BTCUSDT", "o-1")]


@pytest.mark.anyio
async def test_adr0002_startup_planning_and_recovery_without_real_app():
    repo = InMemoryTaskRepository()
    running_cfg = json.dumps(
        [
            {
                "task_type": "TRADER",
                "symbol": "BTC-USDT",
                "interval": "1m",
                "strategy": "macd_triple_divergence",
                "live_execution_mode": "auto_trade",
                "run_id": "run-55",
                "user_id": 7,
            }
        ]
    )
    done_cfg = json.dumps([{"task_type": "DEBUG", "limit": 1}])
    await repo.add_tasks(
        [
            _make_state(55, "55.TRADER.BTCUSDT-1m", state=TaskStateType.RUNNING, config_json=running_cfg, user_id=7),
            _make_state(56, "56.DEBUG.BTCUSDT-1h", state=TaskStateType.DONE, config_json=done_cfg, user_id=7),
        ]
    )
    startup_cfgs = [_live_cfg(1, user_id=1)]

    api_plan = await PlanStartupTasks(repo).execute(is_server=True, startup_tasks=startup_cfgs)
    console_plan = await PlanStartupTasks(repo).execute(is_server=False, startup_tasks=startup_cfgs)

    assert api_plan.startup_tasks == []
    assert [t.id for t in api_plan.recover_tasks] == [55]
    assert api_plan.recover_tasks[0].run_id == "run-55"
    assert [t.id for t in console_plan.startup_tasks] == [1]
    assert console_plan.recover_tasks == []

    recovered: list[int] = []
    exchange = _FakeExchange()

    async def _recover_one(cfg: TaskConfig):
        recovered.append(cfg.id)

    await RecoverRunningTasks().execute(api_plan.recover_tasks, _recover_one)
    assert recovered == [55]
    assert exchange.canceled_orders == []
    assert exchange.canceled_symbols == []


@pytest.mark.anyio
async def test_single_running_task_per_user_and_submit_stop_fund_lifecycle_without_real_app():
    repo = InMemoryTaskRepository()
    reservations = _FakeReservationStore()
    exec_store = _FakeExecutionStateStore([_exec_record(task_id=10, key="k10", symbol="BTCUSDT", order_id="ord-10")])
    exchange = _FakeExchange(balances={"USDT": 500.0})

    await repo.add_tasks(
        [
            _make_state(
                10,
                "10.TRADER.BTCUSDT-1m",
                state=TaskStateType.RUNNING,
                config_json=json.dumps(
                    [
                        {
                            "task_type": "TRADER",
                            "symbol": "BTC-USDT",
                            "interval": "1m",
                            "strategy": "macd_triple_divergence",
                            "live_execution_mode": "auto_trade",
                        }
                    ]
                ),
                user_id=7,
            ),
            _make_state(
                20,
                "20.TRADER.ETHUSDT-1m",
                state=TaskStateType.RUNNING,
                config_json=json.dumps(
                    [
                        {
                            "task_type": "TRADER",
                            "symbol": "ETH-USDT",
                            "interval": "1m",
                            "strategy": "macd_triple_divergence",
                            "live_execution_mode": "auto_trade",
                        }
                    ]
                ),
                user_id=8,
            ),
        ]
    )
    await reservations.reserve(
        account_key="BINANCE:user:7:default",
        exchange="BINANCE",
        credential_id=None,
        user_id=7,
        task_id=10,
        asset="USDT",
        amount=100.0,
        capacity=500.0,
        reason="live_task_start",
    )

    stop_uc = StopTask(
        task_repository=repo,
        fund_reservation_store=reservations,
        execution_state_store=exec_store,
        exchange_resolver=lambda _cfg: exchange,
    )
    stopped = await StopUserRunningTasks(repo, stop_uc).execute(user_id=7)

    assert stopped == [10]
    assert (await repo.get_task(10)).state == TaskStateType.DONE
    assert (await repo.get_task(20)).state == TaskStateType.RUNNING
    assert exchange.canceled_orders == [("BTCUSDT", "ord-10")]
    assert (10, "task_closed") in reservations.released

    runner = _FakeTaskRunner()
    submit_uc = SubmitTasks(
        task_repository=repo,
        task_runner=runner,
        preflight_funds=PreflightLiveTaskFunds(
            exchange_resolver=lambda _cfg: exchange,
            account_key_resolver=lambda cfg: f"BINANCE:user:{cfg.user_id}:default",
        ),
        release_funds=ReleaseTaskFunds(reservations),
    )
    new_cfg = _live_cfg(30, user_id=7, max_notional=150.0)
    await submit_uc.execute([new_cfg])

    assert runner.started == [30]
    assert new_cfg.fund_reservation_amount == 150.0
    assert (await repo.get_task(30)).state == TaskStateType.DONE
    assert (30, "task_done") in reservations.released

    failing_submit = SubmitTasks(
        task_repository=repo,
        task_runner=_FakeTaskRunner(fail=True),
        preflight_funds=PreflightLiveTaskFunds(
            exchange_resolver=lambda _cfg: exchange,
            account_key_resolver=lambda cfg: f"BINANCE:user:{cfg.user_id}:default",
        ),
        release_funds=ReleaseTaskFunds(reservations),
    )
    fail_cfg = _live_cfg(31, user_id=7, max_notional=150.0)
    with pytest.raises(RuntimeError, match="boom-31"):
        await failing_submit.execute([fail_cfg])

    failed_state = await repo.get_task(31)
    assert failed_state.state == TaskStateType.FAILED
    assert "boom-31" in (failed_state.error_message or "")
    assert (31, "task_failed") in reservations.released


@pytest.mark.anyio
async def test_fund_reservation_preflight_and_recovery_budget_restore():
    exchange = _FakeExchange(balances={"USDT": 60.0}, borrowables={"USDT": 50.0})
    preflight = PreflightLiveTaskFunds(
        exchange_resolver=lambda _cfg: exchange,
        account_key_resolver=lambda cfg: f"BINANCE:user:{cfg.user_id}:default",
    )

    short_cfg = _live_cfg(40, max_notional=100.0, chainer_mode="BOTH")
    await preflight.execute([short_cfg])
    assert short_cfg.fund_reservation_amount == 100.0
    assert short_cfg.fund_reservation_remaining == 100.0

    over_cfg = _live_cfg(41, max_notional=120.0, chainer_mode="BOTH")
    with pytest.raises(FundReservationError, match="insufficient live task balance"):
        await preflight.execute([over_cfg])

    exec_store = _FakeExecutionStateStore([_exec_record(task_id=40, key="e1", notional=35.0)])
    restore = RestoreRecoveredTaskBudget(
        execution_state_store=exec_store,
        exchange_resolver=lambda _cfg: _FakeExchange(balances={"USDT": 1.0}),
        account_key_resolver=lambda cfg: f"BINANCE:user:{cfg.user_id}:default",
    )
    recovered_cfg = _live_cfg(40, max_notional=100.0, chainer_mode="BOTH")
    await restore.execute(recovered_cfg)
    assert recovered_cfg.fund_reservation_amount == 100.0
    assert recovered_cfg.fund_reservation_remaining == pytest.approx(65.0)
