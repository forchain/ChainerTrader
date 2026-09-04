import os
from decimal import Decimal
from types import SimpleNamespace
import time

import pytest

from trader.exchange.binance.exchange import BinanceExchange
from trader.exchange.driver import ExchangeDriverType
from trader.exchange.exchange_config import ExchangeConfig
from trader.execution.models import GatewayCapability
from trader.tools.binance_live_smoke import (
    LiveSmokeReport,
    _attach_breakeven_update,
    _cancel_all_open_orders,
    _cleanup_blocking_orders_for_acceptance,
    _env_driver_type,
    _final_acceptance_gate,
    _is_actionable_reason,
    _latest_price,
    _list_open_orders_for_acceptance,
    _is_force_majeure_reason,
    _safe_replacement_stop_price,
    _verify_entry_with_protection,
    _verify_replace_protection,
    _stop_loss_order_id_from_outcome,
    _run_objective_with_resilience,
    run_binance_live_smoke_from_env,
)
from trader.utils.operate import Operate, OperateType
from trader.utils.symbol_interval import Symbol


@pytest.mark.skipif(
    os.getenv("CHAINERTRADER_ENABLE_BINANCE_LIVE_E2E") != "1",
    reason="requires CHAINERTRADER_ENABLE_BINANCE_LIVE_E2E=1 and real Binance credentials; places real orders",
)
def test_binance_live_smoke_covers_chainer_protection_and_macd_metadata():
    missing = [name for name in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "CHAINERTRADER_SMALL_LIVE_MAX_NOTIONAL") if not os.getenv(name)]
    if missing:
        pytest.skip(f"Binance live smoke config missing: {', '.join(missing)}")

    report = run_binance_live_smoke_from_env()

    assert report.passed, report.to_dict()
    step_names = {step.name for step in report.steps if step.status == "passed"}
    skipped_names = {step.name for step in report.steps if step.status == "skipped"}
    if os.getenv("CHAINERTRADER_LIVE_SMOKE_ENABLE_SPOT") == "1":
        assert {"spot_long_entry", "spot_long_close"}.issubset(step_names)
    if os.getenv("CHAINERTRADER_LIVE_SMOKE_ENABLE_MARGIN") == "1":
        margin_passed = {"margin_short_entry", "margin_short_close"}.issubset(step_names)
        margin_force_majeure = "margin_short_flow_skipped_force_majeure" in skipped_names
        assert margin_passed or margin_force_majeure


def test_live_smoke_defaults_to_ccxt_driver(monkeypatch):
    monkeypatch.delenv("CHAINERTRADER_LIVE_SMOKE_DRIVER", raising=False)

    assert _env_driver_type() == ExchangeDriverType.CCXT


def test_live_smoke_can_explicitly_select_binance_native_driver(monkeypatch):
    monkeypatch.setenv("CHAINERTRADER_LIVE_SMOKE_DRIVER", "binance_native")

    assert _env_driver_type() == ExchangeDriverType.BINANCE_NATIVE


def test_live_smoke_requires_trader_db_for_execution_state_verification(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "s")
    monkeypatch.setenv("CHAINERTRADER_SMALL_LIVE_MAX_NOTIONAL", "11")
    monkeypatch.setenv("CHAINERTRADER_LIVE_SMOKE_ENABLE_SPOT", "1")
    monkeypatch.setenv("CHAINERTRADER_LIVE_SMOKE_ENABLE_MARGIN", "1")
    monkeypatch.delenv("TRADER_DB", raising=False)

    with pytest.raises(RuntimeError, match="TRADER_DB is required"):
        run_binance_live_smoke_from_env()


def test_live_smoke_requires_single_run_dual_flow(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "s")
    monkeypatch.setenv("CHAINERTRADER_SMALL_LIVE_MAX_NOTIONAL", "11")
    monkeypatch.setenv("TRADER_DB", "mongodb://localhost:27017/")
    monkeypatch.setenv("CHAINERTRADER_LIVE_SMOKE_ENABLE_SPOT", "0")
    monkeypatch.setenv("CHAINERTRADER_LIVE_SMOKE_ENABLE_MARGIN", "1")

    with pytest.raises(RuntimeError, match="single-run dual-flow"):
        run_binance_live_smoke_from_env()


def test_ccxt_backed_binance_exchange_declares_protection_capabilities():
    exchange = BinanceExchange(ExchangeConfig(driver=ExchangeDriverType.CCXT))

    assert GatewayCapability.PROTECTIVE_STOP in exchange.supported_gateway_capabilities()
    assert GatewayCapability.TAKE_PROFIT_LIMIT in exchange.supported_gateway_capabilities()
    assert GatewayCapability.OCO_PROTECTION in exchange.supported_gateway_capabilities()
    assert GatewayCapability.BREAKEVEN_REPLACEMENT in exchange.supported_gateway_capabilities()


def test_live_smoke_cancel_all_open_orders_uses_exchange_adapter_without_spot_client():
    class FakeCcxtBackedExchange:
        spot_client = None
        margin_mode = None

        def __init__(self):
            self.calls = []

        def cancel_all_open_orders(self, symbol):
            self.calls.append(symbol.name())
            return [{"id": "stop-1", "status": "canceled"}]

    exchange = FakeCcxtBackedExchange()
    report = LiveSmokeReport(symbol="BTCUSDT", notional=11.0, spot_enabled=True, margin_enabled=False)

    _cancel_all_open_orders(exchange, Symbol("BTC-USDT"), report, step_prefix="spot")

    assert exchange.calls == ["BTCUSDT"]
    assert report.steps[-1].name == "spot_cancel_open_orders"
    assert report.steps[-1].status == "passed"


def test_cleanup_blocking_orders_for_acceptance_records_before_after_cancel_evidence():
    class FakeExchange:
        def __init__(self):
            self.canceled = False

        def get_open_orders(self, _symbol):
            if self.canceled:
                return []
            return [
                {"id": "o1", "symbol": "BTC/USDT", "side": "buy", "type": "stop_loss", "status": "open"},
                {"id": "o2", "symbol": "BTC/USDT", "side": "buy", "type": "take_profit", "status": "open"},
            ]

        def get_open_protection_orders(self, _symbol):
            if self.canceled:
                return []
            return [
                SimpleNamespace(exchange_order_ids=("o1",), protection_id="p1"),
                SimpleNamespace(exchange_order_ids=("o2",), protection_id="p2"),
            ]

        def cancel_all_open_orders(self, _symbol):
            self.canceled = True
            return [{"orderId": "o1", "status": "CANCELED"}, {"orderId": "o2", "status": "CANCELED"}]

    report = LiveSmokeReport(symbol="BTCUSDT", notional=11.0, spot_enabled=True, margin_enabled=True)
    evidence = _cleanup_blocking_orders_for_acceptance(
        report=report,
        symbol=Symbol("BTC-USDT"),
        exchanges=[("margin", FakeExchange())],
    )

    assert evidence["final_residual_count"] == 0
    assert evidence["scopes"][0]["open_order_count_before"] == 2
    assert evidence["scopes"][0]["open_order_ids_before"] == ["o1", "o2"]
    assert evidence["scopes"][0]["open_order_count_after"] == 0
    assert evidence["scopes"][0]["open_order_ids_after"] == []
    assert report.steps[-1].name == "test_000_cleanup_blocking_orders"
    assert report.steps[-1].status == "passed"


def test_cleanup_blocking_orders_for_acceptance_fails_when_residual_orders_remain():
    class FakeExchange:
        def get_open_orders(self, _symbol):
            return [{"id": "still-open", "symbol": "BTC/USDT", "side": "buy", "type": "stop_loss", "status": "open"}]

        def get_open_protection_orders(self, _symbol):
            return [SimpleNamespace(exchange_order_ids=("still-open",), protection_id="p1")]

        def cancel_all_open_orders(self, _symbol):
            return [{"orderId": "still-open", "status": "REJECTED"}]

    report = LiveSmokeReport(symbol="BTCUSDT", notional=11.0, spot_enabled=True, margin_enabled=True)
    with pytest.raises(RuntimeError, match="residual blocking orders remain"):
        _cleanup_blocking_orders_for_acceptance(
            report=report,
            symbol=Symbol("BTC-USDT"),
            exchanges=[("margin", FakeExchange())],
        )

    assert report.steps[-1].name == "test_000_cleanup_blocking_orders"
    assert report.steps[-1].status == "failed"


def test_list_open_orders_for_acceptance_checks_spot_and_cross_margin_before_cleanup():
    class FakeExchange:
        def __init__(self, orders):
            self.orders = orders

        def get_open_orders(self, _symbol):
            return self.orders

    report = LiveSmokeReport(symbol="BTCUSDT", notional=11.0, spot_enabled=True, margin_enabled=True)
    evidence = _list_open_orders_for_acceptance(
        report=report,
        symbol=Symbol("BTC-USDT"),
        exchanges=[
            ("spot", FakeExchange([])),
            (
                "cross_margin",
                FakeExchange(
                    [
                        {
                            "id": "m1",
                            "symbol": "BTC/USDT",
                            "side": "buy",
                            "type": "stop_loss",
                            "amount": 0.00013,
                            "stopPrice": 100000,
                            "status": "open",
                        }
                    ]
                ),
            ),
        ],
    )

    assert evidence["scopes"][0]["scope"] == "spot"
    assert evidence["scopes"][0]["open_order_count"] == 0
    assert evidence["scopes"][1]["scope"] == "cross_margin"
    assert evidence["scopes"][1]["open_order_count"] == 1
    assert evidence["scopes"][1]["open_orders"][0]["order_id"] == "m1"
    assert report.steps[-1].name == "test_000a_list_open_orders"
    assert report.steps[-1].status == "passed"


def test_list_open_orders_for_acceptance_passes_with_zero_counts_for_manual_review():
    class FakeExchange:
        def get_open_orders(self, _symbol):
            return []

    report = LiveSmokeReport(symbol="BTCUSDT", notional=11.0, spot_enabled=True, margin_enabled=True)
    evidence = _list_open_orders_for_acceptance(
        report=report,
        symbol=Symbol("BTC-USDT"),
        exchanges=[("spot", FakeExchange()), ("cross_margin", FakeExchange())],
    )

    assert report.steps[-1].name == "test_000a_list_open_orders"
    assert report.steps[-1].status == "passed"
    assert evidence["scopes"][0]["open_order_count"] == 0
    assert evidence["scopes"][1]["open_order_count"] == 0


def test_latest_price_reads_binance_oneof_wrappers():
    class ActualInstance:
        def __init__(self, price):
            self.price = price

    class WrappedResponse:
        def __init__(self, price):
            self.actual_instance = ActualInstance(price)

    class FakeRestApi:
        def ticker_price(self, symbol):
            return SimpleNamespace(data=lambda: WrappedResponse("79866.20000000"))

    class FakeExchange:
        spot_client = SimpleNamespace(rest_api=FakeRestApi())

    assert _latest_price(FakeExchange(), Symbol("BTC-USDT")) == Decimal("79866.20000000")


def test_preflight_exchange_fails_when_open_protection_orders_exist_without_cancel_capability():
    class FakeExchange:
        def exchange_info(self, _symbol):
            return {"symbols": [{"filters": [{"filterType": "LOT_SIZE", "stepSize": "0.000001", "minQty": "0.000001"}]}]}

        def get_latest_klines(self, _si, _limit):
            return [SimpleNamespace(close=80000.0)]

        def get_open_protection_orders(self, _symbol):
            return [SimpleNamespace(protection_id="p1"), SimpleNamespace(protection_id="p2")]

        def is_cross_margin_ready(self):
            return True

    report = LiveSmokeReport(symbol="BTCUSDT", notional=11.0, spot_enabled=True, margin_enabled=True)
    with pytest.raises(RuntimeError, match="does not support cancel_all_open_orders"):
        from trader.tools.binance_live_smoke import _preflight_exchange

        _preflight_exchange(FakeExchange(), Symbol("BTC-USDT"), Decimal("11"), require_margin=False, report=report)


def test_preflight_exchange_auto_cleans_orders_before_failing():
    class FakeExchange:
        def __init__(self):
            self.canceled = 0

        def exchange_info(self, _symbol):
            return {"symbols": [{"filters": [{"filterType": "LOT_SIZE", "stepSize": "0.000001", "minQty": "0.000001"}]}]}

        def get_latest_klines(self, _si, _limit):
            return [SimpleNamespace(close=80000.0)]

        def get_open_protection_orders(self, _symbol):
            if self.canceled == 0:
                return [SimpleNamespace(protection_id="p1")]
            return []

        def cancel_all_open_orders(self, _symbol):
            self.canceled += 1
            return [{"id": "p1", "status": "canceled"}]

        def is_cross_margin_ready(self):
            return True

    from trader.tools.binance_live_smoke import _preflight_exchange

    exchange = FakeExchange()
    report = LiveSmokeReport(symbol="BTCUSDT", notional=11.0, spot_enabled=True, margin_enabled=True)
    _preflight_exchange(exchange, Symbol("BTC-USDT"), Decimal("11"), require_margin=False, report=report)

    names = [step.name for step in report.steps]
    assert "preflight_cancel_open_orders" in names
    assert "preflight_spot" in names


def test_force_majeure_reason_classifier():
    assert _is_force_majeure_reason("RequestTimeout: read timed out") is True
    assert _is_force_majeure_reason("invalid api-key format") is True
    assert _is_force_majeure_reason("binance GET https://api.binance.com/sapi/v1/capital/config/getall") is True
    assert _is_force_majeure_reason("insufficient_quote_balance") is True
    assert _is_force_majeure_reason("MAX_NUM_ALGO_ORDERS") is False


def test_objective_resilience_skips_force_majeure_and_continues():
    report = LiveSmokeReport(symbol="BTCUSDT", notional=11.0, spot_enabled=True, margin_enabled=True)
    hard_failures: list[str] = []

    def objective():
        raise RuntimeError("RequestTimeout: read timed out")

    _run_objective_with_resilience(
        report=report,
        objective_name="margin_short_flow",
        objective=objective,
        hard_failures=hard_failures,
    )

    assert hard_failures == []
    assert report.steps[-1].name == "margin_short_flow_skipped_force_majeure"
    assert report.steps[-1].status == "skipped"


def test_objective_resilience_keeps_non_force_majeure_as_failure():
    report = LiveSmokeReport(symbol="BTCUSDT", notional=11.0, spot_enabled=True, margin_enabled=True)
    hard_failures: list[str] = []

    def objective():
        raise RuntimeError('binance {"code":-2010,"msg":"Filter failure: MAX_NUM_ALGO_ORDERS"}')

    _run_objective_with_resilience(
        report=report,
        objective_name="margin_short_flow",
        objective=objective,
        hard_failures=hard_failures,
    )

    assert len(hard_failures) == 1
    assert "MAX_NUM_ALGO_ORDERS" in hard_failures[0]
    assert report.steps[-1].name == "margin_short_flow_failed"
    assert report.steps[-1].status == "failed"


def test_live_smoke_passed_requires_all_steps_passed():
    report = LiveSmokeReport(symbol="BTCUSDT", notional=11.0, spot_enabled=True, margin_enabled=True)
    report.add("a", "passed")
    report.add("b", "skipped")
    assert report.passed is False


def test_final_acceptance_gate_requires_required_steps_and_execution_state_records():
    report = LiveSmokeReport(
        symbol="BTCUSDT",
        notional=11.0,
        spot_enabled=True,
        margin_enabled=True,
        acceptance_contract={
            "max_minutes": 15,
            "required_steps": [
                "spot_long_entry",
                "spot_long_breakeven_replace",
                "spot_long_close",
            ],
        },
    )
    report.add("spot_long_entry", "passed", execution_state_records=[{"id": "1"}])
    report.add("spot_long_breakeven_replace", "passed", execution_state_records=[{"id": "2"}])
    report.add("spot_long_close", "passed", execution_state_records=[{"id": "3"}])
    _final_acceptance_gate(report=report, started_at_ms=int(time.time() * 1000))


def test_verify_entry_with_protection_uses_verify_order_ids_fallback_when_open_orders_empty():
    class FakeExchange:
        def get_open_protection_orders(self, _symbol):
            return []

        def verify_order_ids(self, _symbol, order_ids):
            return order_ids == ["p-new-1"]

    outcome = SimpleNamespace(
        exchange_order={"orderId": "entry-1"},
        execution_events=[
            {"event_type": "order_submitted", "order_id": "entry-1"},
            {"event_type": "order_accepted", "order_id": "entry-1"},
            {
                "event_type": "protection_armed",
                "order_id": "p-new-1",
                "metadata": {"raw_payload": {"orderId": "p-new-1"}},
            },
        ],
    )
    verification = _verify_entry_with_protection(
        exchange=FakeExchange(),
        symbol=Symbol("BTC-USDT"),
        outcome=outcome,
        label="spot long entry",
        previous_protection_ids=set(),
    )
    assert verification["verification_mode"] == "verify_order_ids_fallback"
    assert verification["protection_order_ids_after"] == ["p-new-1"]


def test_verify_replace_protection_uses_verify_order_ids_fallback_when_open_orders_empty():
    class FakeExchange:
        def get_open_protection_orders(self, _symbol):
            return []

        def verify_order_ids(self, _symbol, order_ids):
            return order_ids == ["p-new-2"]

    outcome = SimpleNamespace(
        exchange_order={"orderId": "replace-1"},
        execution_events=[
            {"event_type": "protection_replaced", "order_id": "p-new-2", "metadata": {"raw_payload": {"orderId": "p-new-2"}}},
        ],
    )
    verification = _verify_replace_protection(
        exchange=FakeExchange(),
        symbol=Symbol("BTC-USDT"),
        outcome=outcome,
        label="spot long breakeven replace",
        protection_ids_before_replace={"p-old-1"},
    )
    assert verification["verification_mode"] == "verify_order_ids_fallback"
    assert verification["protection_order_ids_after"] == ["p-new-2"]
    assert verification["added_new_protection_order_ids"] == ["p-new-2"]


def test_breakeven_update_carries_old_stop_loss_order_id_for_live_replace():
    outcome = SimpleNamespace(
        execution_events=[
            {
                "event_type": "protection_armed",
                "order_id": "stop-1,tp-1",
                "metadata": {
                    "raw_payload": {
                        "orders": [
                            {"orderId": "stop-1", "type": "STOP_LOSS"},
                            {"orderId": "tp-1", "type": "TAKE_PROFIT"},
                        ]
                    }
                },
            }
        ]
    )

    old_stop_id = _stop_loss_order_id_from_outcome(outcome)
    op = Operate(OperateType.RISK_UPDATE, 1_714_281_660, 100000.0)
    _attach_breakeven_update(
        op,
        direction="SHORT",
        trace_id="trade-1",
        old_stop=105000.0,
        new_stop=100000.0,
        old_protection_order_id=old_stop_id,
    )

    assert old_stop_id == "stop-1"
    assert op.protection_order_id == "stop-1"
    assert op.framework_trade["protection_order_id"] == "stop-1"


def test_safe_replacement_stop_price_stays_non_triggering_around_current_price():
    price = Decimal("100")

    assert _safe_replacement_stop_price(price, direction="LONG", fallback_offset=Decimal("0.05")) < price
    assert _safe_replacement_stop_price(price, direction="SHORT", fallback_offset=Decimal("0.05")) > price


def test_final_acceptance_gate_fails_when_required_step_missing():
    report = LiveSmokeReport(
        symbol="BTCUSDT",
        notional=11.0,
        spot_enabled=True,
        margin_enabled=True,
        acceptance_contract={"required_steps": ["spot_long_entry", "spot_long_close"]},
    )
    report.add("spot_long_entry", "passed", execution_state_records=[{"id": "1"}])
    with pytest.raises(RuntimeError, match="required steps missing/failed"):
        _final_acceptance_gate(report=report, started_at_ms=int(time.time() * 1000))


def test_final_acceptance_gate_fails_when_execution_state_records_missing():
    report = LiveSmokeReport(
        symbol="BTCUSDT",
        notional=11.0,
        spot_enabled=True,
        margin_enabled=True,
        acceptance_contract={"required_steps": ["spot_long_entry"]},
    )
    report.add("spot_long_entry", "passed", execution_state_records=[])
    with pytest.raises(RuntimeError, match="execution_state_records missing"):
        _final_acceptance_gate(report=report, started_at_ms=int(time.time() * 1000))


def test_actionable_reason_classifier():
    assert _is_actionable_reason("Filter failure: MAX_NUM_ALGO_ORDERS") is True
    assert _is_actionable_reason("open_orders exists") is True
    assert _is_actionable_reason("RequestTimeout read timed out") is False


def test_binance_exchange_normalize_quantity_reads_oneof_wrapped_exchange_info():
    class ActualInstance:
        def __init__(self, symbols):
            self.symbols = symbols

    class WrappedInfo:
        def __init__(self, symbols):
            self.actual_instance = ActualInstance(symbols)

    class Filter:
        def __init__(self, step_size, min_qty):
            self.filterType = "LOT_SIZE"
            self.stepSize = step_size
            self.minQty = min_qty

    class SymbolInfo:
        def __init__(self):
            self.filters = [Filter("0.000001", "0.000001")]

    class FakeExchange:
        def exchange_info(self, symbol):
            return WrappedInfo([SymbolInfo()])

    normalized = BinanceExchange._normalize_quantity(FakeExchange(), Symbol("BTC-USDT"), 0.00013783623426395764)

    assert normalized == 0.000137


def test_binance_exchange_normalize_price_reads_oneof_wrapped_exchange_info():
    class ActualInstance:
        def __init__(self, symbols):
            self.symbols = symbols

    class WrappedInfo:
        def __init__(self, symbols):
            self.actual_instance = ActualInstance(symbols)

    class Filter:
        def __init__(self, tick_size, min_price):
            self.filterType = "PRICE_FILTER"
            self.tickSize = tick_size
            self.minPrice = min_price

    class SymbolInfo:
        def __init__(self):
            self.filters = [Filter("0.01", "0.01")]

    class FakeExchange:
        def exchange_info(self, symbol):
            return WrappedInfo([SymbolInfo()])

    normalized = BinanceExchange._normalize_price(FakeExchange(), Symbol("BTC-USDT"), 83785.1805)

    assert normalized == 83785.18
