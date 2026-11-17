from types import SimpleNamespace

import pytest

from trader.common.config import Config
from trader.live.auto_execution import AutoExecutionRouter, AutoExecutionStatus
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.utils.operate import Operate, OperateType
from trader.utils.symbol_interval import Interval, SymbolInterval


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _router(**tcfg_overrides) -> AutoExecutionRouter:
    cfg = Config(tasks="[]", cash=1000.0)
    options = {"live_execution_mode": "auto_trade", **tcfg_overrides}
    tcfg = TaskConfig(
        9,
        TaskType.TRADER,
        SymbolInterval("BTC-USDT", Interval("1m")),
        strategies=["ShihunRSI"],
        free=500.0,
        **options,
    )
    return AutoExecutionRouter(tcfg, exchange=None, cfg=cfg, log=None)


def _record(**kwargs):
    defaults = {
        "idempotency_key": "k",
        "intent_id": "i",
        "operation_id": "o",
        "gateway": "live",
        "staged_execution_mode": "auto_trade",
        "symbol": "BTCUSDT",
        "order_role": "entry",
        "status": "submitted",
        "quantity": 0.0,
        "raw_payload": {},
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_reconcile_rehydrates_long_short_and_protection_ids():
    router = _router()
    records = [
        _record(order_role="entry", quantity=2.0, raw_payload={"side": "long"}, trade_id="t1"),
        _record(order_role="entry", quantity=1.5, raw_payload={"side": "short"}, trade_id="t2"),
        _record(order_role="stop_loss", quantity=2.0, raw_payload={"side": "long"}, trade_id="t1", protection_id="stop-1"),
        _record(order_role="take_profit", quantity=2.0, raw_payload={"side": "long"}, trade_id="t1", exchange_order_id="tp-1"),
    ]

    payload = router.reconcile(records)

    assert router.real_long_position == 2.0
    assert router.real_short_position == 1.5
    assert router._protection_order_ids_by_trade == {"t1": "tp-1"}
    assert len(payload) == 4


def test_reconcile_resets_stale_exposure():
    router = _router()
    router.real_long_position = 10.0
    router.real_short_position = 10.0
    router._protection_order_ids_by_trade = {"old": "old-id"}

    router.reconcile([])

    assert router.real_long_position == 0.0
    assert router.real_short_position == 0.0
    assert router._protection_order_ids_by_trade == {}


def test_router_owns_manual_notify_state():
    router = _router(live_execution_mode="manual_notify")
    entry = Operate(OperateType.LONG, 1, 10.0)
    exit_op = Operate(OperateType.SELL, 2, 12.0)

    entry_event = router.handle_manual_trade_notifications(SimpleNamespace(opts=[entry]))[0]
    exit_event = router.handle_manual_trade_notifications(SimpleNamespace(opts=[exit_op]))[0]

    assert entry_event.local_state.cash_after == 0.0
    assert entry_event.local_state.position_after == 50.0
    assert exit_event.local_state.position_after == 0.0
    assert router.manual_cash == 600.0
    assert router.manual_position == 0.0


def test_spot_and_margin_submission_share_one_pipeline():
    router = _router()

    assert hasattr(router, "_submit_order")
    assert not hasattr(router, "_submit_spot")
    assert not hasattr(router, "_submit_margin")


@pytest.mark.anyio
async def test_persist_outcome_owns_state_records_and_budget_deduction():
    router = _router()
    saved = []
    spent = []

    class Store:
        async def save(self, record):
            saved.append(record)
            return record

    class ReservationStore:
        async def mark_spent(self, task_id, asset, notional):
            spent.append((task_id, asset, notional))

    outcome = SimpleNamespace(
        execution_state_records=["record-1"],
        status=AutoExecutionStatus.SUBMITTED,
        effective_notional=25.0,
        operation_id="op-1",
        operation_type="LONG",
        reason=None,
    )

    await router.persist_outcome(outcome, state_store=Store(), reservation_store=ReservationStore())

    assert saved == ["record-1"]
    assert spent == [(9, "USDT", 25.0)]
