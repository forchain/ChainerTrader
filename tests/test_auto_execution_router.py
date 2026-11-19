from types import SimpleNamespace

import pytest

from trader.adapters.outbound.files.task_config_loader import TaskConfig
from trader.core.execution import ExecutionStatus
from trader.core.execution.use_cases import AutoExecutionRouter, AutoExecutionStatus
from trader.core.shared.config import Config
from trader.core.shared.domain import Interval, Operate, OperateType, SymbolInterval
from trader.core.task.domain import TaskType


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _StubGateway:
    """Placeholder gateway; tests that route install their own double."""

    capabilities = SimpleNamespace(gateway="live")


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
    return AutoExecutionRouter(tcfg, exchange=None, cfg=cfg, log=None, gateway=_StubGateway())


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


def test_manual_notify_state_is_owned_by_the_live_session():
    """Manual-notify cash/position state lives in the session, not in the router."""
    router = _router(live_execution_mode="manual_notify")

    assert not hasattr(router, "handle_manual_trade_notifications")
    assert not hasattr(router, "manual_cash")
    assert not hasattr(router, "manual_position")


def test_spot_and_margin_submission_use_separate_pipelines():
    router = _router()

    assert hasattr(router, "_submit_spot")
    assert hasattr(router, "_submit_margin")


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


def test_reconcile_nets_close_records_and_drops_terminal_entries():
    router = _router()
    records = [
        _record(order_role="entry", quantity=2.0, raw_payload={"side": "long"}, trade_id="t1"),
        _record(order_role="entry", quantity=1.5, raw_payload={"side": "short"}, trade_id="t2"),
        _record(order_role="entry", quantity=3.0, raw_payload={"side": "long"}, trade_id="t3", status="failed"),
        _record(order_role="close", quantity=2.0, raw_payload={"side": "long"}, trade_id="t1"),
        _record(order_role="stop_loss", quantity=2.0, raw_payload={"side": "long"}, trade_id="t1", protection_id="stop-1"),
    ]

    router.reconcile(records)

    assert router.real_long_position == 0.0
    assert router.real_short_position == 1.5
    assert router._protection_order_ids_by_trade == {}


def test_reconcile_partial_close_never_goes_negative():
    router = _router()
    records = [
        _record(order_role="entry", quantity=1.0, raw_payload={"side": "long"}, trade_id="t1"),
        _record(order_role="close", quantity=2.0, raw_payload={"side": "long"}, trade_id="t1"),
    ]

    router.reconcile(records)

    assert router.real_long_position == 0.0


class _MarginExchange:
    def __init__(self, balance: float = 1000.0):
        self.balance = balance

    def is_cross_margin_ready(self):
        return True

    def get_account_balance(self, asset):
        return self.balance


def _margin_router(**overrides):
    options = {"strategy_params": {"chainer_mode": "BOTH"}, "fund_reservation_amount": 500.0, **overrides}
    router = _router(**options)
    router.exchange = _MarginExchange()
    return router


def test_margin_long_path_uses_the_margin_submission_pipeline():
    router = _margin_router()
    submitted = SimpleNamespace(status=AutoExecutionStatus.SUBMITTED)
    calls = []

    def fake_submit(*args, **kwargs):
        calls.append(kwargs)
        return submitted

    router._submit_margin = fake_submit
    outcome = router._route_real_long(Operate(OperateType.BUY, 1, 10.0), 10.0)

    assert outcome is submitted
    assert calls, "the margin path must submit through the margin pipeline"


def test_margin_exit_uses_the_margin_submission_pipeline():
    router = _margin_router()
    router.real_long_position = 50.0
    submitted = SimpleNamespace(status=AutoExecutionStatus.SUBMITTED)
    router._submit_margin = lambda *args, **kwargs: submitted

    outcome = router._route_real_exit(Operate(OperateType.SELL, 2, 10.0), 10.0)

    assert outcome is submitted


def test_margin_borrow_retry_protection_failure_triggers_fail_safe_close():
    from trader.core.execution import ExecutionSide, ExecutionStatus
    from trader.core.execution.order_semantics import select_order_semantics

    router = _margin_router(live_margin_borrow_block_policy="repay_single")

    class RepayExchange(_MarginExchange):
        def auto_repay_for_borrow_block(self, symbol):
            return {"ok": True}

    router.exchange = RepayExchange()

    op = Operate(OperateType.LONG, 1, 10.0)
    op.framework_trade = {"trade_id": "t1"}
    op.stop_loss = 9.0
    selection = select_order_semantics(op, symbol="BTCUSDT", side=ExecutionSide.LONG, quantity=50.0, notional=500.0)

    initial = SimpleNamespace(accepted=False, reason="-3006 borrow blocked", events=[], gateway_order_id=None, status=ExecutionStatus.REJECTED)
    retry = SimpleNamespace(accepted=True, reason=None, events=[], gateway_order_id="entry-1", status=ExecutionStatus.ACCEPTED)
    protection = SimpleNamespace(accepted=False, reason="protection_rejected", events=[], gateway_order_id=None, status=ExecutionStatus.REJECTED)
    closed = SimpleNamespace(accepted=True, reason=None, events=[], gateway_order_id="close-1", status=ExecutionStatus.ACCEPTED)

    class Gateway:
        def __init__(self):
            self.closed_intents = []

        def open_position(self, intent):
            return retry

        def place_protection(self, intent):
            return protection

        def close_position(self, intent):
            self.closed_intents.append(intent)
            return closed

    gateway = Gateway()
    outcome = router._handle_margin_borrow_block(
        op=op,
        notional=500.0,
        quantity=50.0,
        gateway=gateway,
        selection=selection,
        initial_result=initial,
        requested_notional=500.0,
        requested_quantity=50.0,
    )

    assert len(gateway.closed_intents) == 1
    assert outcome.status == AutoExecutionStatus.FAILED
    assert any(getattr(record, "order_role", "") == "close" for record in outcome.execution_state_records)


class _RecordingGateway:
    """Execution gateway double that records the intents it received."""

    def __init__(self, fail_protection: bool = False):
        self.opened = []
        self.closed = []
        self.fail_protection = fail_protection

    def open_position(self, intent):
        self.opened.append(intent)
        return SimpleNamespace(
            accepted=True,
            reason=None,
            events=[],
            gateway_order_id="entry-1",
            status=ExecutionStatus.ACCEPTED,
        )

    def close_position(self, intent):
        self.closed.append(intent)
        return SimpleNamespace(
            accepted=True,
            reason=None,
            events=[],
            gateway_order_id="close-1",
            status=ExecutionStatus.ACCEPTED,
        )

    def place_protection(self, intent):
        if self.fail_protection:
            return SimpleNamespace(
                accepted=False,
                reason="protection_rejected",
                events=[],
                gateway_order_id=None,
                status=ExecutionStatus.REJECTED,
            )
        return SimpleNamespace(
            accepted=True,
            reason=None,
            events=[],
            gateway_order_id="stop-1",
            status=ExecutionStatus.ACCEPTED,
        )


def test_submit_spot_path_submits_and_records_entry():
    router = _router()
    gateway = _RecordingGateway()
    router.gateway = gateway

    outcome = router._submit_spot(Operate(OperateType.BUY, 1, 10.0), 500.0, 50.0, OperateType.BUY)

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert len(gateway.opened) == 1
    assert [record.order_role for record in outcome.execution_state_records] == ["entry"]


def test_submit_spot_protection_failure_triggers_fail_safe_close():
    router = _router()
    gateway = _RecordingGateway(fail_protection=True)
    router.gateway = gateway
    op = Operate(OperateType.BUY, 1, 10.0)
    op.stop_loss = 9.0

    outcome = router._submit_spot(op, 500.0, 50.0, OperateType.BUY)

    assert outcome.status == AutoExecutionStatus.FAILED
    assert len(gateway.opened) == 1
    assert len(gateway.closed) == 1
    assert any(record.order_role == "close" for record in outcome.execution_state_records)
