from types import SimpleNamespace

import pytest

from trader.live.auto_execution import (
    AUTO_EXECUTION_EVENT_TYPE,
    AutoExecutionRouter,
    AutoExecutionStatus,
    LiveExecutionMode,
    execution_outcome_event,
    operation_identity,
)
from trader.live.monitor import build_initial_snapshot
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.utils.kline import Kline
from trader.utils.operate import Operate, OperateType
from trader.utils.symbol_interval import Interval, SymbolInterval

BASE = 1_714_281_600


@pytest.fixture
def anyio_backend():
    return "asyncio"


class RecordingExchange:
    def __init__(self, *, quote_balance=10_000.0, base_balance=0.0, margin_ready=True):
        self.quote_balance = quote_balance
        self.base_balance = base_balance
        self.margin_ready = margin_ready
        self.new_order_calls = []
        self.margin_order_calls = []
        self.oco_order_calls = []
        self.stop_order_calls = []
        self.take_profit_order_calls = []
        self.replace_stop_order_calls = []
        self.balance_reads = []
        self.max_borrowable_reads = []

    def get_account_balance(self, asset):
        self.balance_reads.append(asset)
        if asset == "USDT":
            return self.quote_balance
        if asset == "BTC":
            return self.base_balance
        return 0.0

    def new_order(self, symbol, op, quantity):
        self.new_order_calls.append((symbol.name(), op, quantity))
        return {"orderId": "spot-1"}

    def new_margin_order(self, symbol, op, quantity):
        self.margin_order_calls.append((symbol.name(), op, quantity))
        return {"orderId": "margin-1"}

    def new_oco_order(self, symbol, side, quantity, stop_price, take_profit_price):
        self.oco_order_calls.append((symbol.name(), side, quantity, stop_price, take_profit_price))
        return {"orderListId": "oco-1", "orders": [{"orderId": "stop-1"}, {"orderId": "tp-1"}]}

    def new_stop_order(self, symbol, side, quantity, stop_price):
        self.stop_order_calls.append((symbol.name(), side, quantity, stop_price))
        return {"orderId": "stop-1"}

    def new_take_profit_order(self, symbol, side, quantity, take_profit_price):
        self.take_profit_order_calls.append((symbol.name(), side, quantity, take_profit_price))
        return {"orderId": "tp-1"}

    def replace_stop_order(self, symbol, side, order_id, quantity, stop_price):
        self.replace_stop_order_calls.append((symbol.name(), side, order_id, quantity, stop_price))
        return {"orderId": "stop-2"}

    def verify_order_ids(self, symbol, order_ids):
        return bool(order_ids)

    def is_cross_margin_ready(self):
        return self.margin_ready

    def auto_repay_for_borrow_block(self, symbol):
        return {"ok": True, "symbol": symbol}

    def auto_repay_all_liabilities_for_borrow_block(
        self,
        symbol,
        *,
        max_total,
        max_per_asset,
        min_amount=0.000001,
        excluded_assets=None,
    ):
        return {
            "ok": True,
            "policy": "repay_all",
            "symbol": symbol,
            "max_total": max_total,
            "max_per_asset": max_per_asset,
            "min_amount": min_amount,
            "excluded_assets": list(excluded_assets or []),
            "total_repaid": min(max_total, max_per_asset),
            "results": [],
        }

    def get_max_borrowable(self, asset, symbol=None):
        self.max_borrowable_reads.append((asset, symbol))
        return {"asset": asset, "amount": "1000000", "borrowLimit": "1000000"}


def _tcfg(
    mode,
    *,
    free=1000.0,
    manual_start_position=0.0,
    live_trade_max_notional=0.0,
    live_margin_borrow_block_policy="skip_continue",
    chainer_mode="LONG_ONLY",
):
    return TaskConfig(
        id=9,
        ttype=TaskType.TRADER,
        symbol_interval=SymbolInterval("BTC-USDT", Interval.INTERVAL_1m),
        strategies=["macd_triple_divergence"],
        free=free,
        manual_start_position=manual_start_position,
        live_execution_mode=mode,
        live_trade_max_notional=live_trade_max_notional,
        live_margin_borrow_block_policy=live_margin_borrow_block_policy,
        strategy_params={"chainer_mode": chainer_mode},
    )


def _short_tcfg(mode, **kwargs):
    return _tcfg(mode, chainer_mode="BOTH", **kwargs)


def _op(otype, price=100.0, dtime=BASE):
    return Operate(otype, dtime, price)


def _cfg(*, cash=10000.0, leverage_ratio=1.0):
    return SimpleNamespace(cash=cash, leverage_ratio=leverage_ratio)


def test_operation_identity_prefers_signal_event_id_and_falls_back_to_side_time_price():
    op = _op(OperateType.BUY, 123.456789)
    op.signal_event_id = "sig-123"
    assert operation_identity(op) == "signal_event_id:sig-123"

    fallback = _op(OperateType.BUY, 123.456789, BASE + 60)
    assert operation_identity(fallback) == "operation:BUY:1714281660:123.456789"


def test_paper_auto_mode_is_rejected_before_routing():
    with pytest.raises(ValueError, match="unsupported live_execution_mode: paper_auto"):
        _tcfg("paper_auto")


def test_auto_trade_caps_real_long_order_by_fixed_notional():
    exchange = RecordingExchange(quote_balance=1000.0)
    router = AutoExecutionRouter(
        _tcfg(LiveExecutionMode.AUTO_TRADE, free=500.0, live_trade_max_notional=25.0),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )

    outcome = router.route(_op(OperateType.BUY, 100.0))

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert outcome.effective_notional == 25.0
    assert outcome.effective_quantity == 0.25
    assert exchange.new_order_calls == [("BTCUSDT", OperateType.BUY, 0.25)]


def test_auto_trade_cap_uses_explicit_max_notional_without_legacy_hint():
    exchange = RecordingExchange(quote_balance=1000.0)
    tcfg = _tcfg(LiveExecutionMode.AUTO_TRADE, free=500.0, live_trade_max_notional=25.0)
    router = AutoExecutionRouter(
        tcfg,
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )

    outcome = router.route(_op(OperateType.BUY, 100.0))

    assert router.mode == LiveExecutionMode.AUTO_TRADE.value
    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert outcome.effective_notional == 25.0
    assert outcome.effective_quantity == 0.25
    assert exchange.new_order_calls == [("BTCUSDT", OperateType.BUY, 0.25)]


def test_auto_trade_places_native_protection_for_stop_and_take_profit():
    exchange = RecordingExchange(quote_balance=1000.0)
    router = AutoExecutionRouter(
        _tcfg(LiveExecutionMode.AUTO_TRADE, free=500.0, live_trade_max_notional=25.0),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )
    op = _op(OperateType.BUY, 100.0)
    op.stop_loss = 95.0
    op.take_profit = 110.0

    outcome = router.route(op)

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert exchange.new_order_calls == [("BTCUSDT", OperateType.BUY, 0.25)]
    assert exchange.oco_order_calls == [("BTCUSDT", OperateType.SELL, 0.25, 95.0, 110.0)]
    assert outcome.native_protection is True
    assert [event["event_type"] for event in outcome.execution_events][-1] == "protection_armed"
    assert [record.order_role for record in outcome.execution_state_records] == ["entry", "bracket"]
    assert [record.status.value for record in outcome.execution_state_records] == ["submitted", "accepted"]
    assert all(record.task_id == 9 for record in outcome.execution_state_records)


def test_auto_trade_spot_close_uses_router_position_not_account_total_balance():
    exchange = RecordingExchange(quote_balance=1000.0, base_balance=0.75)
    router = AutoExecutionRouter(
        _tcfg(LiveExecutionMode.AUTO_TRADE, live_trade_max_notional=25.0),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )

    entry = router.route(_op(OperateType.BUY, 100.0))
    close = router.route(_op(OperateType.SELL, 110.0, BASE + 60))

    assert entry.status == AutoExecutionStatus.SUBMITTED
    assert close.status == AutoExecutionStatus.SUBMITTED
    assert close.effective_quantity == 0.25
    assert exchange.new_order_calls == [
        ("BTCUSDT", OperateType.BUY, 0.25),
        ("BTCUSDT", OperateType.SELL, 0.25),
    ]


def test_live_auto_rejects_side_invalid_protection_before_order_submission():
    exchange = RecordingExchange(quote_balance=1000.0)
    router = AutoExecutionRouter(
        _tcfg(LiveExecutionMode.AUTO_TRADE, live_trade_max_notional=25.0),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )
    op = _op(OperateType.BUY, 100.0)
    op.stop_loss = 105.0

    outcome = router.route(op)

    assert outcome.status == AutoExecutionStatus.SKIPPED
    assert outcome.reason == "long stop_price must be below entry_price"
    assert exchange.new_order_calls == []
    assert exchange.oco_order_calls == []


def test_auto_trade_skips_when_requested_notional_invalid_or_balance_insufficient():
    invalid_notional = AutoExecutionRouter(
        _tcfg(LiveExecutionMode.AUTO_TRADE, free=0.0, live_trade_max_notional=0.0),
        exchange=RecordingExchange(),
        cfg=SimpleNamespace(cash=10000.0),
    ).route(_op(OperateType.BUY, 100.0))
    assert invalid_notional.status == AutoExecutionStatus.SKIPPED
    assert invalid_notional.reason == "invalid_notional"

    exchange = RecordingExchange(quote_balance=5.0)
    insufficient = AutoExecutionRouter(
        _tcfg(LiveExecutionMode.AUTO_TRADE, live_trade_max_notional=25.0),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    ).route(_op(OperateType.BUY, 100.0))
    assert insufficient.status == AutoExecutionStatus.SKIPPED
    assert insufficient.reason == "insufficient_quote_balance"
    assert exchange.new_order_calls == []


def test_auto_trade_without_max_notional_uses_configured_free_sizing():
    exchange = RecordingExchange(quote_balance=1000.0)
    router = AutoExecutionRouter(
        _tcfg(LiveExecutionMode.AUTO_TRADE, free=500.0, live_trade_max_notional=0.0),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )

    outcome = router.route(_op(OperateType.BUY, 100.0))

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert outcome.effective_notional == 500.0
    assert outcome.effective_quantity == 5.0


def test_margin_long_caps_full_live_requested_exposure_by_leverage_ratio():
    exchange = RecordingExchange(quote_balance=60.0, margin_ready=True)
    router = AutoExecutionRouter(
        _short_tcfg(LiveExecutionMode.AUTO_TRADE, free=500.0),
        exchange=exchange,
        cfg=_cfg(leverage_ratio=2.0),
    )

    outcome = router.route(_op(OperateType.BUY, 100.0))

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert outcome.requested_notional == 500.0
    assert outcome.effective_notional == 120.0
    assert outcome.effective_quantity == 1.2
    assert exchange.new_order_calls == [("BTCUSDT", OperateType.BUY, 1.2)]
    assert exchange.max_borrowable_reads == [("USDT", "BTCUSDT")]


def test_margin_leverage_ratio_caps_but_does_not_auto_enlarge_requested_size():
    exchange = RecordingExchange(quote_balance=60.0, margin_ready=True)
    router = AutoExecutionRouter(
        _short_tcfg(LiveExecutionMode.AUTO_TRADE, free=60.0),
        exchange=exchange,
        cfg=_cfg(leverage_ratio=2.0),
    )

    outcome = router.route(_op(OperateType.BUY, 100.0))

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert outcome.requested_notional == 60.0
    assert outcome.effective_notional == 60.0
    assert outcome.effective_quantity == 0.6
    assert exchange.new_order_calls == [("BTCUSDT", OperateType.BUY, 0.6)]
    assert exchange.max_borrowable_reads == []


def test_small_live_margin_hard_cap_is_not_enlarged_by_leverage_ratio():
    exchange = RecordingExchange(quote_balance=60.0, margin_ready=True)
    router = AutoExecutionRouter(
        _short_tcfg(LiveExecutionMode.AUTO_TRADE, live_trade_max_notional=10.0),
        exchange=exchange,
        cfg=_cfg(leverage_ratio=2.0),
    )

    outcome = router.route(_op(OperateType.BUY, 100.0))

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert outcome.requested_notional == 10.0
    assert outcome.effective_notional == 10.0
    assert outcome.effective_quantity == 0.1
    assert exchange.new_order_calls == [("BTCUSDT", OperateType.BUY, 0.1)]
    assert exchange.max_borrowable_reads == []


def test_real_auto_entry_skips_when_reserved_budget_is_too_small_even_if_exchange_balance_is_available():
    exchange = RecordingExchange(quote_balance=1000.0)
    tcfg = _tcfg(LiveExecutionMode.AUTO_TRADE, free=50.0)
    tcfg.fund_reservation_amount = 20.0
    router = AutoExecutionRouter(
        tcfg,
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )

    outcome = router.route(_op(OperateType.BUY, 100.0))

    assert outcome.status == AutoExecutionStatus.SKIPPED
    assert outcome.reason == "insufficient_reserved_funds"
    assert exchange.new_order_calls == []


def test_real_auto_entry_marks_reserved_budget_spent_after_successful_submit():
    exchange = RecordingExchange(quote_balance=1000.0)
    tcfg = _tcfg(LiveExecutionMode.AUTO_TRADE, free=50.0)
    tcfg.fund_reservation_amount = 50.0
    router = AutoExecutionRouter(
        tcfg,
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )

    outcome = router.route(_op(OperateType.BUY, 100.0))

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert exchange.new_order_calls == [("BTCUSDT", OperateType.BUY, 0.5)]
    assert router._reserved_budget_remaining == 0.0


def test_real_short_is_skipped_for_long_only_and_both_mode_short_uses_margin_path():
    disabled_exchange = RecordingExchange()
    disabled = AutoExecutionRouter(
        _tcfg(LiveExecutionMode.AUTO_TRADE, live_trade_max_notional=10.0, chainer_mode="LONG_ONLY"),
        exchange=disabled_exchange,
        cfg=SimpleNamespace(cash=10000.0),
    ).route(_op(OperateType.SHORT, 100.0))
    assert disabled.status == AutoExecutionStatus.SKIPPED
    assert disabled.reason == "short_capability_not_required"
    assert disabled_exchange.new_order_calls == []
    assert disabled_exchange.margin_order_calls == []

    margin_exchange = RecordingExchange(margin_ready=True)
    submitted = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
        ),
        exchange=margin_exchange,
        cfg=SimpleNamespace(cash=10000.0),
    ).route(_op(OperateType.SHORT, 100.0))
    assert submitted.status == AutoExecutionStatus.SUBMITTED
    assert submitted.effective_quantity == 0.1
    assert margin_exchange.new_order_calls == [("BTCUSDT", OperateType.SHORT, 0.1)]
    assert margin_exchange.margin_order_calls == []


def test_cross_margin_short_places_native_buy_side_protection_when_configured():
    exchange = RecordingExchange(margin_ready=True)
    router = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
        ),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )
    op = _op(OperateType.SHORT, 100.0)
    op.stop_loss = 105.0
    op.take_profit = 90.0

    outcome = router.route(op)

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert outcome.native_protection is True
    assert outcome.effective_quantity == 0.1
    assert outcome.reason is None
    assert outcome.native_protection is True


def test_cross_margin_short_risk_update_replaces_buy_side_stop_with_short_exposure():
    exchange = RecordingExchange(margin_ready=True)
    router = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
        ),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )
    entry = _op(OperateType.SHORT, 100.0)
    entry.stop_loss = 105.0
    assert router.route(entry).status == AutoExecutionStatus.SUBMITTED

    update = _op(OperateType.RISK_UPDATE, 100.0, BASE + 60)
    update.framework_trade = {"trade_id": "trade-1", "direction": "SHORT"}
    update.breakeven_new_stop = 100.0
    update.protection_order_id = "stop-1"
    outcome = router.route(update)

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert exchange.replace_stop_order_calls == [("BTCUSDT", OperateType.CLOSE, "stop-1", 0.1, 100.0)]
    assert outcome.execution_state_records[0].order_role == "replace_stop"


def test_live_auto_submits_fail_safe_close_when_required_protection_is_unverified():
    class UnverifiedProtectionExchange(RecordingExchange):
        def verify_order_ids(self, symbol, order_ids):
            return False

    exchange = UnverifiedProtectionExchange(quote_balance=1000.0)
    router = AutoExecutionRouter(
        _tcfg(LiveExecutionMode.AUTO_TRADE, free=500.0, live_trade_max_notional=25.0),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )
    op = _op(OperateType.BUY, 100.0)
    op.stop_loss = 95.0
    op.take_profit = 110.0

    outcome = router.route(op)

    assert outcome.status == AutoExecutionStatus.FAILED
    assert outcome.reason == "native_protection_unverified; fail_safe_close_submitted"
    assert exchange.new_order_calls == [
        ("BTCUSDT", OperateType.BUY, 0.25),
        ("BTCUSDT", OperateType.SELL, 0.25),
    ]
    assert [event["event_type"] for event in outcome.execution_events].count("protection_missing") == 1
    assert [record.order_role for record in outcome.execution_state_records] == ["entry", "bracket", "close"]


def test_live_auto_submits_fail_safe_close_when_protection_order_is_rejected_by_exchange():
    class RejectStopProtectionExchange(RecordingExchange):
        def new_stop_order(self, symbol, side, quantity, stop_price):
            raise RuntimeError("binance Stop price would trigger immediately.")

    exchange = RejectStopProtectionExchange(quote_balance=1000.0)
    router = AutoExecutionRouter(
        _tcfg(LiveExecutionMode.AUTO_TRADE, free=500.0, live_trade_max_notional=25.0),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )
    op = _op(OperateType.BUY, 100.0)
    op.stop_loss = 95.0

    outcome = router.route(op)

    assert outcome.status == AutoExecutionStatus.FAILED
    assert outcome.reason == "gateway_rejected; fail_safe_close_submitted"
    assert exchange.new_order_calls == [
        ("BTCUSDT", OperateType.BUY, 0.25),
        ("BTCUSDT", OperateType.SELL, 0.25),
    ]
    assert [event["event_type"] for event in outcome.execution_events].count("protection_missing") == 1
    assert [record.order_role for record in outcome.execution_state_records] == ["entry", "stop_loss", "close"]


def test_cross_margin_short_close_requires_known_short_exposure():
    unknown_exchange = RecordingExchange(margin_ready=True)
    unknown = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
        ),
        exchange=unknown_exchange,
        cfg=SimpleNamespace(cash=10000.0),
    ).route(_op(OperateType.CLOSE, 90.0))
    assert unknown.status == AutoExecutionStatus.SKIPPED
    assert unknown.reason == "unknown_short_exposure"
    assert unknown_exchange.margin_order_calls == []

    exchange = RecordingExchange(margin_ready=True)
    router = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
        ),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )
    entry = router.route(_op(OperateType.SHORT, 100.0))
    close = router.route(_op(OperateType.CLOSE, 90.0, BASE + 60))

    assert entry.status == AutoExecutionStatus.SUBMITTED
    assert close.status == AutoExecutionStatus.SUBMITTED
    assert close.effective_quantity == 0.1
    assert exchange.new_order_calls == [
        ("BTCUSDT", OperateType.SHORT, 0.1),
        ("BTCUSDT", OperateType.CLOSE, 0.1),
    ]
    assert exchange.margin_order_calls == []


def test_short_capable_tasks_use_margin_for_long_and_exit_when_margin_is_ready():
    exchange = RecordingExchange(margin_ready=True)
    router = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
        ),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )

    entry = router.route(_op(OperateType.BUY, 100.0))
    assert entry.status == AutoExecutionStatus.SUBMITTED
    assert entry.native_protection is False
    assert entry.effective_quantity == 0.1


def test_spot_execution_does_not_apply_leverage_ratio_cap():
    exchange = RecordingExchange(quote_balance=5.0, margin_ready=False)
    router = AutoExecutionRouter(
        _tcfg(LiveExecutionMode.AUTO_TRADE, live_trade_max_notional=10.0, chainer_mode="LONG_ONLY"),
        exchange=exchange,
        cfg=_cfg(leverage_ratio=2.0),
    )

    outcome = router.route(_op(OperateType.BUY, 100.0))

    assert outcome.status == AutoExecutionStatus.SKIPPED
    assert outcome.reason == "insufficient_quote_balance"
    assert exchange.new_order_calls == []
    assert exchange.max_borrowable_reads == []


def test_long_only_stays_on_spot_path_even_when_margin_is_ready():
    exchange = RecordingExchange(quote_balance=1000.0, base_balance=0.75, margin_ready=True)
    router = AutoExecutionRouter(
        _tcfg(LiveExecutionMode.AUTO_TRADE, live_trade_max_notional=25.0, chainer_mode="LONG_ONLY"),
        exchange=exchange,
        cfg=_cfg(leverage_ratio=2.0),
    )

    entry = router.route(_op(OperateType.BUY, 100.0))
    close = router.route(_op(OperateType.SELL, 110.0, BASE + 60))

    assert entry.status == AutoExecutionStatus.SUBMITTED
    assert entry.effective_notional == 25.0
    assert entry.effective_quantity == 0.25
    assert close.status == AutoExecutionStatus.SUBMITTED
    assert close.effective_quantity == 0.25
    assert exchange.new_order_calls == [
        ("BTCUSDT", OperateType.BUY, 0.25),
        ("BTCUSDT", OperateType.SELL, 0.25),
    ]
    assert exchange.max_borrowable_reads == []


def test_margin_borrow_block_skip_policy_skips_short_and_continues():
    class BorrowBlockedExchange(RecordingExchange):
        def __init__(self):
            super().__init__(margin_ready=True)
            self.short_calls = 0
            self.repay_calls = 0

        def new_order(self, symbol, op, quantity):
            self.new_order_calls.append((symbol.name(), op, quantity))
            if op == OperateType.SHORT:
                self.short_calls += 1
                return {"code": -3006, "msg": "Your borrow amount has exceed maximum borrow amount"}
            return {"orderId": "spot-1"}

        def auto_repay_for_borrow_block(self, symbol):
            self.repay_calls += 1
            return {"ok": True, "symbol": symbol}

    exchange = BorrowBlockedExchange()
    router = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
            live_margin_borrow_block_policy="skip_continue",
        ),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )

    short_outcome = router.route(_op(OperateType.SHORT, 100.0))
    long_outcome = router.route(_op(OperateType.BUY, 100.0, BASE + 60))

    assert short_outcome.status == AutoExecutionStatus.SKIPPED
    assert "margin_borrow_blocked_-3006" in str(short_outcome.reason)
    assert exchange.repay_calls == 0
    assert long_outcome.status == AutoExecutionStatus.SUBMITTED


def test_margin_borrow_block_stop_task_policy_fails_short():
    class BorrowBlockedExchange(RecordingExchange):
        def __init__(self):
            super().__init__(margin_ready=True)

        def new_order(self, symbol, op, quantity):
            self.new_order_calls.append((symbol.name(), op, quantity))
            if op == OperateType.SHORT:
                return {"code": -3006, "msg": "Your borrow amount has exceed maximum borrow amount"}
            return {"orderId": "spot-1"}

    exchange = BorrowBlockedExchange()
    router = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
            live_margin_borrow_block_policy="stop_task",
        ),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )

    short_outcome = router.route(_op(OperateType.SHORT, 100.0))
    assert short_outcome.status == AutoExecutionStatus.FAILED
    assert "stop_task" in str(short_outcome.reason)


def test_margin_borrow_block_repay_single_policy_retries_once_and_submits():
    class BorrowBlockedThenPassExchange(RecordingExchange):
        def __init__(self):
            super().__init__(margin_ready=True)
            self.short_calls = 0
            self.repay_calls = 0

        def new_order(self, symbol, op, quantity):
            self.new_order_calls.append((symbol.name(), op, quantity))
            if op == OperateType.SHORT:
                self.short_calls += 1
                if self.short_calls == 1:
                    return {"code": -3006, "msg": "Your borrow amount has exceed maximum borrow amount"}
                return {"orderId": "margin-retry-1"}
            return {"orderId": "spot-1"}

        def auto_repay_for_borrow_block(self, symbol):
            self.repay_calls += 1
            return {"ok": True, "symbol": symbol}

    exchange = BorrowBlockedThenPassExchange()
    router = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
            live_margin_borrow_block_policy="repay_single",
        ),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )

    outcome = router.route(_op(OperateType.SHORT, 100.0))
    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert "auto_repay_retry_passed" in str(outcome.reason)
    assert exchange.short_calls == 2
    assert exchange.repay_calls == 1


def test_margin_borrow_block_exception_triggers_auto_repay_retry_with_capacity_context():
    class BorrowBlockedExceptionThenPassExchange(RecordingExchange):
        def __init__(self):
            super().__init__(base_balance=0.02, margin_ready=True)
            self.short_calls = 0
            self.repay_calls = 0

        def new_order(self, symbol, op, quantity):
            self.new_order_calls.append((symbol.name(), op, quantity))
            if op == OperateType.SHORT:
                self.short_calls += 1
                if self.short_calls == 1:
                    raise RuntimeError('binance {"code":-3006,"msg":"Your borrow amount has exceed maximum borrow amount."}')
                return {"orderId": "margin-retry-1"}
            return {"orderId": "spot-1"}

        def auto_repay_for_borrow_block(self, symbol):
            self.repay_calls += 1
            return {
                "ok": True,
                "symbol": symbol,
                "results": [
                    {
                        "asset": "BTC",
                        "status": "repaid",
                        "amount": 0.01,
                        "borrowed": 0.01,
                        "interest": 0.0,
                        "free": 0.02,
                    }
                ],
            }

    exchange = BorrowBlockedExceptionThenPassExchange()
    router = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
            live_margin_borrow_block_policy="repay_single",
        ),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )

    outcome = router.route(_op(OperateType.SHORT, 100.0))

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert "auto_repay_retry_passed" in str(outcome.reason)
    assert exchange.short_calls == 2
    assert exchange.repay_calls == 1
    assert outcome.margin_borrow_control["trigger"] == "binance_-3006"
    assert outcome.margin_borrow_control["borrow_capacity"]["asset"] == "BTC"
    assert outcome.margin_borrow_control["borrow_capacity"]["balance"] == 0.02
    assert outcome.margin_borrow_control["borrow_capacity"]["estimated_shortfall"] == pytest.approx(0.08)
    assert outcome.margin_borrow_control["borrow_capacity"]["max_borrowable"] == 1000000.0
    assert outcome.margin_borrow_control["repay"]["results"][0]["amount"] == 0.01


def test_margin_long_leverage_cap_ignores_quote_borrow_capacity_when_cap_removes_shortfall():
    class LowBorrowCapacityExchange(RecordingExchange):
        def get_max_borrowable(self, asset, symbol=None):
            self.max_borrowable_reads.append((asset, symbol))
            return {"asset": asset, "amount": "4.0", "borrowLimit": "4.0"}

    exchange = LowBorrowCapacityExchange(quote_balance=5.0, margin_ready=True)
    router = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
        ),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )

    outcome = router.route(_op(OperateType.BUY, 100.0))

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert outcome.requested_notional == 10.0
    assert outcome.effective_notional == 5.0
    assert outcome.effective_quantity == 0.05
    assert exchange.max_borrowable_reads == []
    assert exchange.new_order_calls == [("BTCUSDT", OperateType.BUY, 0.05)]


def test_margin_long_leverage_cap_prevents_unnecessary_borrow_precheck_when_shortfall_is_removed():
    exchange = RecordingExchange(quote_balance=5.0, margin_ready=True)
    router = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
        ),
        exchange=exchange,
        cfg=_cfg(leverage_ratio=1.0),
    )

    outcome = router.route(_op(OperateType.BUY, 100.0))

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert outcome.requested_notional == 10.0
    assert outcome.effective_notional == 5.0
    assert outcome.effective_quantity == 0.05
    assert exchange.new_order_calls == [("BTCUSDT", OperateType.BUY, 0.05)]
    assert exchange.max_borrowable_reads == []


def test_leverage_cap_falls_back_to_cfg_cash_when_live_quote_balance_is_unreadable():
    class UnreadableBalanceExchange:
        def __init__(self):
            self.new_order_calls = []

        def get_account_balance(self, asset):
            raise RuntimeError("balance unavailable")

        def new_order(self, symbol, op, quantity):
            self.new_order_calls.append((symbol.name(), op, quantity))
            return {"orderId": "spot-1"}

        def is_cross_margin_ready(self):
            return True

    tcfg = _short_tcfg(
        LiveExecutionMode.AUTO_TRADE,
        free=-1.0,
        live_trade_max_notional=100.0,
    )
    exchange = UnreadableBalanceExchange()
    router = AutoExecutionRouter(
        tcfg,
        exchange=exchange,
        cfg=_cfg(cash=30.0, leverage_ratio=2.0),
    )

    outcome = router.route(_op(OperateType.BUY, 100.0))

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert outcome.requested_notional == 100.0
    assert outcome.effective_notional == 60.0
    assert outcome.effective_quantity == 0.6
    assert exchange.new_order_calls == [("BTCUSDT", OperateType.BUY, 0.6)]


def test_margin_borrow_precheck_skips_margin_short_when_base_borrow_capacity_is_too_low():
    class LowBorrowCapacityExchange(RecordingExchange):
        def get_max_borrowable(self, asset, symbol=None):
            self.max_borrowable_reads.append((asset, symbol))
            return {"asset": asset, "amount": "0.05", "borrowLimit": "0.05"}

    exchange = LowBorrowCapacityExchange(base_balance=0.02, margin_ready=True)
    router = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
        ),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )

    outcome = router.route(_op(OperateType.SHORT, 100.0))

    assert outcome.status == AutoExecutionStatus.SKIPPED
    assert str(outcome.reason).startswith("margin_borrow_precheck_insufficient_capacity")
    assert "asset=BTC" in str(outcome.reason)
    assert exchange.max_borrowable_reads == [("BTC", "BTCUSDT")]
    assert exchange.new_order_calls == []


def test_margin_short_applies_leverage_cap_on_quote_notional_before_borrow_capacity_check():
    class BorrowCapacityExchange(RecordingExchange):
        def get_max_borrowable(self, asset, symbol=None):
            self.max_borrowable_reads.append((asset, symbol))
            return {"asset": asset, "amount": "0.07", "borrowLimit": "0.07"}

    exchange = BorrowCapacityExchange(quote_balance=6.0, base_balance=0.0, margin_ready=True)
    router = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
        ),
        exchange=exchange,
        cfg=_cfg(leverage_ratio=1.0),
    )

    outcome = router.route(_op(OperateType.SHORT, 100.0))

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert outcome.requested_notional == 10.0
    assert outcome.effective_notional == 6.0
    assert outcome.effective_quantity == 0.06
    assert exchange.max_borrowable_reads == [("BTC", "BTCUSDT")]
    assert exchange.new_order_calls == [("BTCUSDT", OperateType.SHORT, 0.06)]


def test_margin_long_leverage_cap_ignores_zero_quote_borrow_capacity_when_cap_removes_shortfall():
    class ZeroBorrowExchange(RecordingExchange):
        def get_max_borrowable(self, asset, symbol=None):
            self.max_borrowable_reads.append((asset, symbol))
            return {"asset": asset, "amount": "0.0", "borrowLimit": "0.0"}

    exchange = ZeroBorrowExchange(quote_balance=5.0, margin_ready=True)
    router = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
        ),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )

    outcome = router.route(_op(OperateType.BUY, 100.0))

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert outcome.requested_notional == 10.0
    assert outcome.effective_notional == 5.0
    assert outcome.effective_quantity == 0.05
    assert exchange.max_borrowable_reads == []
    assert exchange.new_order_calls == [("BTCUSDT", OperateType.BUY, 0.05)]


def test_margin_borrow_block_repay_single_policy_handles_margin_long_orders():
    class LongBorrowBlockedThenPassExchange(RecordingExchange):
        def __init__(self):
            super().__init__(margin_ready=True)
            self.long_calls = 0
            self.repay_calls = 0

        def new_order(self, symbol, op, quantity):
            self.new_order_calls.append((symbol.name(), op, quantity))
            if op == OperateType.BUY:
                self.long_calls += 1
                if self.long_calls == 1:
                    return {"code": -3006, "msg": "Your borrow amount has exceed maximum borrow amount"}
                return {"orderId": "margin-long-retry-1"}
            return {"orderId": "spot-1"}

        def auto_repay_for_borrow_block(self, symbol):
            self.repay_calls += 1
            return {"ok": True, "symbol": symbol}

    exchange = LongBorrowBlockedThenPassExchange()
    router = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
            live_margin_borrow_block_policy="repay_single",
        ),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )

    outcome = router.route(_op(OperateType.BUY, 100.0))

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert "auto_repay_retry_passed" in str(outcome.reason)
    assert exchange.long_calls == 2
    assert exchange.repay_calls == 1


def test_margin_borrow_block_repay_single_policy_retries_once_then_skips():
    class BorrowBlockedAlwaysExchange(RecordingExchange):
        def __init__(self):
            super().__init__(margin_ready=True)
            self.short_calls = 0
            self.repay_calls = 0

        def new_order(self, symbol, op, quantity):
            self.new_order_calls.append((symbol.name(), op, quantity))
            if op == OperateType.SHORT:
                self.short_calls += 1
                return {"code": -3006, "msg": "Your borrow amount has exceed maximum borrow amount"}
            return {"orderId": "spot-1"}

        def auto_repay_for_borrow_block(self, symbol):
            self.repay_calls += 1
            return {"ok": True, "symbol": symbol}

    exchange = BorrowBlockedAlwaysExchange()
    router = AutoExecutionRouter(
        _short_tcfg(
            LiveExecutionMode.AUTO_TRADE,
            live_trade_max_notional=10.0,
            live_margin_borrow_block_policy="repay_single",
        ),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )

    outcome = router.route(_op(OperateType.SHORT, 100.0))
    assert outcome.status == AutoExecutionStatus.SKIPPED
    assert "auto_repay_retry_failed" in str(outcome.reason)
    assert exchange.short_calls == 2
    assert exchange.repay_calls == 1


def test_margin_borrow_block_repay_all_policy_uses_account_level_repay_report():
    class BorrowBlockedThenPassExchange(RecordingExchange):
        def __init__(self):
            super().__init__(margin_ready=True)
            self.short_calls = 0
            self.repay_all_calls = []

        def new_order(self, symbol, op, quantity):
            self.new_order_calls.append((symbol.name(), op, quantity))
            if op == OperateType.SHORT:
                self.short_calls += 1
                if self.short_calls == 1:
                    return {"code": -3006, "msg": "Your borrow amount has exceed maximum borrow amount"}
                return {"orderId": "margin-retry-1"}
            return {"orderId": "spot-1"}

        def auto_repay_all_liabilities_for_borrow_block(
            self,
            symbol,
            *,
            max_total,
            max_per_asset,
            min_amount=0.000001,
            excluded_assets=None,
        ):
            self.repay_all_calls.append((symbol, max_total, max_per_asset, min_amount, list(excluded_assets or [])))
            return {
                "ok": True,
                "policy": "repay_all",
                "symbol": symbol,
                "total_repaid": 25.0,
                "results": [{"asset": "ETH", "status": "repaid", "amount": 25.0}],
            }

    exchange = BorrowBlockedThenPassExchange()
    tcfg = _short_tcfg(
        LiveExecutionMode.AUTO_TRADE,
        live_trade_max_notional=10.0,
        live_margin_borrow_block_policy="repay_all",
    )
    tcfg.live_margin_auto_repay_max_total = 100.0
    tcfg.live_margin_auto_repay_max_per_asset = 50.0
    tcfg.live_margin_auto_repay_min_amount = 0.000001
    tcfg.live_margin_auto_repay_excluded_assets = ["BNB"]
    router = AutoExecutionRouter(tcfg, exchange=exchange, cfg=SimpleNamespace(cash=10000.0))

    outcome = router.route(_op(OperateType.SHORT, 100.0))

    assert outcome.status == AutoExecutionStatus.SUBMITTED
    assert outcome.margin_borrow_control["policy"] == "repay_all"
    assert outcome.margin_borrow_control["repay"]["total_repaid"] == 25.0
    assert exchange.repay_all_calls == [("BTCUSDT", 100.0, 50.0, 0.000001, ["BNB"])]


def test_duplicate_operation_is_skipped_before_second_execution():
    exchange = RecordingExchange(quote_balance=1000.0)
    router = AutoExecutionRouter(
        _tcfg(LiveExecutionMode.AUTO_TRADE, live_trade_max_notional=25.0),
        exchange=exchange,
        cfg=SimpleNamespace(cash=10000.0),
    )
    op = _op(OperateType.BUY, 100.0)
    op.signal_event_id = "dup"

    first = router.route(op)
    second = router.route(op)

    assert first.status == AutoExecutionStatus.SUBMITTED
    assert second.status == AutoExecutionStatus.SKIPPED
    assert second.reason == "duplicate_operation"
    assert len(exchange.new_order_calls) == 1


@pytest.mark.anyio
async def test_execution_outcomes_are_visible_in_dashboard_events_and_snapshot():
    outcome = AutoExecutionRouter(
        _tcfg(LiveExecutionMode.AUTO_TRADE, live_trade_max_notional=25.0),
        exchange=RecordingExchange(quote_balance=1000.0),
        cfg=SimpleNamespace(cash=10000.0),
    ).route(_op(OperateType.BUY, 100.0))
    event = execution_outcome_event(9, outcome)
    task = SimpleNamespace(
        tcfg=_tcfg(LiveExecutionMode.AUTO_TRADE, live_trade_max_notional=25.0),
        ts=SimpleNamespace(state=SimpleNamespace(name="RUNNING"), tret=SimpleNamespace(opts=[]), auto_execution_outcomes=[outcome]),
    )
    db = SimpleNamespace(kline=SimpleNamespace(get_latest_klines=lambda name, limit: [Kline(BASE, 99, 101, 98, 100, BASE + 59, 1, 1, 1, 1, 1)]))

    snapshot = await build_initial_snapshot(task, db)

    assert event.event_type == AUTO_EXECUTION_EVENT_TYPE
    assert event.payload["status"] == "submitted"
    assert snapshot["auto_execution_outcomes"][0]["status"] == "submitted"
    assert snapshot["auto_execution_outcomes"][0]["effective_notional"] == 25.0
