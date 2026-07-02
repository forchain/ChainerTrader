from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Any
from uuid import uuid4

from trader.common.config import Config
from trader.common.logger import Logger
from trader.exchange.binance.exchange import BinanceExchange
from trader.exchange.driver import ExchangeDriverType
from trader.exchange.exchange_config import ExchangeConfig, MarginMode
from trader.live.auto_execution import AutoExecutionRouter, AutoExecutionStatus
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.utils.operate import Operate, OperateType
from trader.utils.symbol_interval import Interval, Symbol, SymbolInterval


@dataclass
class LiveSmokeStep:
    name: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class LiveSmokeReport:
    symbol: str
    notional: float
    spot_enabled: bool
    margin_enabled: bool
    steps: list[LiveSmokeStep] = field(default_factory=list)
    acceptance_contract: dict[str, Any] = field(default_factory=dict)
    manual_verification: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        for step in self.steps:
            if step.status == "failed":
                return False
            if step.status == "skipped" and "skipped_force_majeure" not in step.name:
                return False
        return True

    def add(self, name: str, status: str, **details: Any) -> None:
        self.steps.append(LiveSmokeStep(name=name, status=status, details=details))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload


def _now_ms() -> int:
    return int(time.time() * 1000)


def run_binance_live_smoke_from_env() -> LiveSmokeReport:
    api_key = os.getenv("BINANCE_API_KEY") or ""
    api_secret = os.getenv("BINANCE_API_SECRET") or ""
    if not api_key or not api_secret:
        raise RuntimeError("BINANCE_API_KEY and BINANCE_API_SECRET are required")

    max_notional = _env_decimal("CHAINERTRADER_SMALL_LIVE_MAX_NOTIONAL", "11")
    hard_limit = _env_decimal("CHAINERTRADER_SMALL_LIVE_HARD_LIMIT", "25")
    if max_notional <= 0:
        raise RuntimeError("CHAINERTRADER_SMALL_LIVE_MAX_NOTIONAL must be positive")
    if max_notional > hard_limit:
        raise RuntimeError(f"live smoke notional {max_notional} exceeds hard limit {hard_limit}")

    raw_symbol = os.getenv("CHAINERTRADER_LIVE_SMOKE_SYMBOL", "BTC-USDT")
    symbol = Symbol(raw_symbol)
    run_spot = os.getenv("CHAINERTRADER_LIVE_SMOKE_ENABLE_SPOT", "1") == "1"
    run_margin = os.getenv("CHAINERTRADER_LIVE_SMOKE_ENABLE_MARGIN", "0") == "1"
    if not run_spot or not run_margin:
        raise RuntimeError("single-run dual-flow verification requires CHAINERTRADER_LIVE_SMOKE_ENABLE_SPOT=1 and CHAINERTRADER_LIVE_SMOKE_ENABLE_MARGIN=1")
    trader_db = os.getenv("TRADER_DB", "").strip()
    if not trader_db:
        raise RuntimeError("TRADER_DB is required for execution_state closure verification")
    driver = _env_driver_type()
    stop_offset = _env_decimal("CHAINERTRADER_LIVE_SMOKE_STOP_OFFSET", "0.05")
    take_profit_offset = _env_decimal("CHAINERTRADER_LIVE_SMOKE_TAKE_PROFIT_OFFSET", "0.05")

    cfg = Config(cash=float(max_notional), window=500)
    log = Logger(cfg).log()
    report = LiveSmokeReport(
        symbol=symbol.name(),
        notional=float(max_notional),
        spot_enabled=run_spot,
        margin_enabled=run_margin,
        acceptance_contract={
            "mode": "single_run_dual_flow",
            "max_minutes": 15,
            "db_required": True,
            "required_steps": [
                "preflight_spot",
                "preflight_margin",
                "spot_long_entry",
                "spot_long_breakeven_replace",
                "spot_long_close",
                "margin_short_entry",
                "margin_short_breakeven_replace",
                "margin_short_close",
            ],
        },
        manual_verification=[
            "Binance Spot Order History: verify spot_long_entry and spot_long_close by order_id.",
            "Binance Margin Order History: verify margin_short_entry and margin_short_close by order_id.",
            "Binance Open Orders: verify no residual protection order after cancel steps.",
            "Binance Trade History/Fee: verify fills and fees exist for each submitted entry/close order.",
            "Execution state DB: verify order/protection records persisted for each submitted step.",
        ],
    )

    hard_failures: list[str] = []
    started_at_ms = _now_ms()

    if run_margin:
        margin_exchange = BinanceExchange(
            ExchangeConfig(
                api_key=api_key,
                api_secret=api_secret,
                margin_mode=MarginMode.CROSS_MARGIN,
                driver=driver,
                base_path=os.getenv("BINANCE_MARGIN_BASE_PATH", "https://api.binance.com"),
            ),
            log,
        )
        _run_objective_with_resilience(
            report=report,
            objective_name="margin_short_flow",
            objective=lambda: (
                _preflight_exchange(margin_exchange, symbol, max_notional, require_margin=True, report=report),
                _run_margin_short_flow(margin_exchange, symbol, max_notional, stop_offset, take_profit_offset, report, cfg),
            ),
            remediation=lambda: _aggressive_symbol_cleanup(
                report=report,
                symbol=symbol,
                exchanges=[("margin", margin_exchange)],
            ),
            hard_failures=hard_failures,
        )
        if hard_failures:
            raise RuntimeError(
                "live smoke halted after margin_short_flow blocker; manual help required: " + " | ".join(hard_failures)
            )
    else:
        report.add("margin_short_flow", "skipped", reason="set CHAINERTRADER_LIVE_SMOKE_ENABLE_MARGIN=1 to test cross-margin short")

    if run_spot:
        exchange = BinanceExchange(
            ExchangeConfig(api_key=api_key, api_secret=api_secret, margin_mode=MarginMode.SPOT, driver=driver),
            log,
        )
        _run_objective_with_resilience(
            report=report,
            objective_name="spot_long_flow",
            objective=lambda: (
                _preflight_exchange(exchange, symbol, max_notional, require_margin=False, report=report),
                _run_spot_long_flow(exchange, symbol, max_notional, stop_offset, take_profit_offset, report, cfg),
            ),
            remediation=lambda: _aggressive_symbol_cleanup(
                report=report,
                symbol=symbol,
                exchanges=[("spot", exchange), ("margin", margin_exchange if run_margin else None)],
            ),
            hard_failures=hard_failures,
        )
        if hard_failures:
            raise RuntimeError(
                "live smoke halted after spot_long_flow blocker; manual help required: " + " | ".join(hard_failures)
            )
    else:
        report.add("spot_long_flow", "skipped", reason="CHAINERTRADER_LIVE_SMOKE_ENABLE_SPOT is not 1")

    if hard_failures:
        raise RuntimeError(
            "live smoke failed with non-force-majeure blockers: " + " | ".join(hard_failures)
        )
    _final_acceptance_gate(report=report, started_at_ms=started_at_ms)

    return report


def cleanup_blocking_orders_from_env() -> LiveSmokeReport:
    api_key = os.getenv("BINANCE_API_KEY") or ""
    api_secret = os.getenv("BINANCE_API_SECRET") or ""
    if not api_key or not api_secret:
        raise RuntimeError("BINANCE_API_KEY and BINANCE_API_SECRET are required")

    max_notional = _env_decimal("CHAINERTRADER_SMALL_LIVE_MAX_NOTIONAL", "11")
    raw_symbol = os.getenv("CHAINERTRADER_LIVE_SMOKE_SYMBOL", "BTC-USDT")
    symbol = Symbol(raw_symbol)
    driver = _env_driver_type()
    cfg = Config(cash=float(max_notional), window=500)
    log = Logger(cfg).log()
    report = LiveSmokeReport(
        symbol=symbol.name(),
        notional=float(max_notional),
        spot_enabled=True,
        margin_enabled=True,
        acceptance_contract={
            "mode": "test_000_cleanup_only",
            "required_steps": ["test_000_cleanup_blocking_orders"],
        },
        manual_verification=[
            f"Binance Spot Open Orders/Conditional/OCO: verify {symbol.name()} reported IDs are canceled or absent.",
            f"Binance Cross Margin Open Orders/Conditional/OCO: verify {symbol.name()} reported IDs are canceled or absent.",
        ],
    )
    spot_exchange = BinanceExchange(
        ExchangeConfig(api_key=api_key, api_secret=api_secret, margin_mode=MarginMode.SPOT, driver=driver),
        log,
    )
    margin_exchange = BinanceExchange(
        ExchangeConfig(
            api_key=api_key,
            api_secret=api_secret,
            margin_mode=MarginMode.CROSS_MARGIN,
            driver=driver,
            base_path=os.getenv("BINANCE_MARGIN_BASE_PATH", "https://api.binance.com"),
        ),
        log,
    )
    _cleanup_blocking_orders_for_acceptance(
        report=report,
        symbol=symbol,
        exchanges=[("spot", spot_exchange), ("margin", margin_exchange)],
    )
    return report


def list_open_orders_from_env() -> LiveSmokeReport:
    api_key = os.getenv("BINANCE_API_KEY") or ""
    api_secret = os.getenv("BINANCE_API_SECRET") or ""
    if not api_key or not api_secret:
        raise RuntimeError("BINANCE_API_KEY and BINANCE_API_SECRET are required")

    max_notional = _env_decimal("CHAINERTRADER_SMALL_LIVE_MAX_NOTIONAL", "11")
    raw_symbol = os.getenv("CHAINERTRADER_LIVE_SMOKE_SYMBOL", "BTC-USDT")
    symbol = Symbol(raw_symbol)
    driver = _env_driver_type()
    cfg = Config(cash=float(max_notional), window=500)
    log = Logger(cfg).log()
    report = LiveSmokeReport(
        symbol=symbol.name(),
        notional=float(max_notional),
        spot_enabled=True,
        margin_enabled=True,
        acceptance_contract={
            "mode": "test_000a_list_open_orders_only",
            "required_steps": ["test_000a_list_open_orders"],
        },
        manual_verification=[
            f"Binance Spot Open Orders: filter {symbol.name()} and compare count/order IDs with spot scope.",
            f"Binance Cross Margin Open Orders: filter {symbol.name()} and compare count/order IDs with cross_margin scope.",
        ],
    )
    spot_exchange = BinanceExchange(
        ExchangeConfig(api_key=api_key, api_secret=api_secret, margin_mode=MarginMode.SPOT, driver=driver),
        log,
    )
    margin_exchange = BinanceExchange(
        ExchangeConfig(
            api_key=api_key,
            api_secret=api_secret,
            margin_mode=MarginMode.CROSS_MARGIN,
            driver=driver,
            base_path=os.getenv("BINANCE_MARGIN_BASE_PATH", "https://api.binance.com"),
        ),
        log,
    )
    _list_open_orders_for_acceptance(
        report=report,
        symbol=symbol,
        exchanges=[("spot", spot_exchange), ("cross_margin", margin_exchange)],
    )
    return report


def _final_acceptance_gate(*, report: LiveSmokeReport, started_at_ms: int) -> None:
    contract = report.acceptance_contract or {}
    max_minutes = int(contract.get("max_minutes", 15))
    required_steps = list(contract.get("required_steps", []))
    elapsed_ms = _now_ms() - started_at_ms
    max_ms = max_minutes * 60 * 1000
    if elapsed_ms > max_ms:
        raise RuntimeError(
            f"acceptance failed: elapsed {elapsed_ms}ms exceeds max_minutes={max_minutes}"
        )
    passed_names = {step.name for step in report.steps if step.status == "passed"}
    skipped_force_majeure_steps = {
        step.name for step in report.steps if step.status == "skipped" and "skipped_force_majeure" in step.name
    }
    missing_steps: list[str] = []
    for name in required_steps:
        if name in passed_names:
            continue
        objective = _objective_from_required_step(name)
        if objective and f"{objective}_skipped_force_majeure" in skipped_force_majeure_steps:
            continue
        missing_steps.append(name)
    if missing_steps:
        raise RuntimeError(
            "acceptance failed: required steps missing/failed: " + ", ".join(missing_steps)
        )
    _validate_execution_state_evidence(report, required_steps, skipped_force_majeure_steps=skipped_force_majeure_steps)


def _validate_execution_state_evidence(
    report: LiveSmokeReport,
    required_steps: list[str],
    *,
    skipped_force_majeure_steps: set[str] | None = None,
) -> None:
    step_map = {step.name: step for step in report.steps}
    execution_required = [name for name in required_steps if name.endswith(("_entry", "_breakeven_replace", "_close"))]
    skipped_force_majeure_steps = skipped_force_majeure_steps or set()
    missing_records: list[str] = []
    for name in execution_required:
        objective = _objective_from_required_step(name)
        if objective and f"{objective}_skipped_force_majeure" in skipped_force_majeure_steps:
            continue
        step = step_map.get(name)
        records = step.details.get("execution_state_records") if step else None
        if not isinstance(records, list) or not records:
            missing_records.append(name)
    if missing_records:
        raise RuntimeError(
            "acceptance failed: execution_state_records missing for steps: "
            + ", ".join(missing_records)
        )


def _objective_from_required_step(step_name: str) -> str | None:
    if step_name.startswith("margin_short_"):
        return "margin_short_flow"
    if step_name.startswith("spot_long_"):
        return "spot_long_flow"
    return None


def _run_spot_long_flow(
    exchange: BinanceExchange,
    symbol: Symbol,
    notional: Decimal,
    _stop_offset: Decimal,
    _take_profit_offset: Decimal,
    report: LiveSmokeReport,
    cfg: Config,
) -> None:
    price = _latest_price(exchange, symbol)
    quantity = _quantity_for_notional(exchange, symbol, notional, price)
    tcfg = _task_config(symbol, notional, chainer_mode="LONG_ONLY")
    router = AutoExecutionRouter(tcfg, exchange=exchange, cfg=cfg)
    trace_id = _trace_id("spot-long")
    entry = _operation(OperateType.BUY, price)
    _attach_macd_like_metadata(
        entry,
        direction="LONG",
        stop_price=float(price * (Decimal("1") - _stop_offset)),
        take_profit=float(price * (Decimal("1") + _take_profit_offset)),
        trace_id=trace_id,
    )

    protection_ids_before_entry: set[str] = _current_protection_order_ids(exchange, symbol)
    try:
        outcome = router.route(entry)
        _require_submitted(outcome, "spot long entry")
        _require_native_protection(outcome, "spot long entry")
        entry_verify = _verify_entry_with_protection(
            exchange=exchange,
            symbol=symbol,
            outcome=outcome,
            label="spot long entry",
            previous_protection_ids=protection_ids_before_entry,
        )
        report.add(
            "spot_long_entry",
            "passed",
            trace_id=trace_id,
            at_ms=_now_ms(),
            quantity=float(quantity),
            order_id=_order_id(outcome.exchange_order),
            native_protection=outcome.native_protection,
            events=[event.get("event_type") for event in outcome.execution_events],
            verification=entry_verify,
            execution_state_records=[asdict(record) for record in outcome.execution_state_records],
            criteria="entry+native_protection_submitted",
        )

        old_stop_protection_id = _stop_loss_order_id_from_outcome(outcome)
        protection_ids_before_replace = set(entry_verify["protection_order_ids_after"])
        risk_update = _operation(OperateType.RISK_UPDATE, price)
        replacement_stop = _safe_replacement_stop_price(
            price,
            direction="LONG",
            fallback_offset=_stop_offset,
        )
        _attach_breakeven_update(
            risk_update,
            direction="LONG",
            trace_id=trace_id,
            old_stop=float(price * (Decimal("1") - _stop_offset)),
            new_stop=float(replacement_stop),
            old_protection_order_id=old_stop_protection_id,
        )
        update_outcome = router.route(risk_update)
        _require_submitted(update_outcome, "spot long breakeven replace")
        replace_verify = _verify_replace_protection(
            exchange=exchange,
            symbol=symbol,
            outcome=update_outcome,
            label="spot long breakeven replace",
            protection_ids_before_replace=protection_ids_before_replace,
        )
        report.add(
            "spot_long_breakeven_replace",
            "passed",
            trace_id=trace_id,
            at_ms=_now_ms(),
            order_id=_order_id(update_outcome.exchange_order),
            old_protection_order_id=old_stop_protection_id,
            native_protection=update_outcome.native_protection,
            events=[event.get("event_type") for event in update_outcome.execution_events],
            verification=replace_verify,
            execution_state_records=[asdict(record) for record in update_outcome.execution_state_records],
            criteria="risk_update_submitted",
        )
    finally:
        _cancel_all_open_orders(exchange, symbol, report, step_prefix="spot")

    close = _operation(OperateType.SELL, price)
    _attach_signal_metadata(close, direction="LONG", trace_id=trace_id)
    close_outcome = router.route(close)
    _require_submitted(close_outcome, "spot long close")
    report.add(
        "spot_long_close",
        "passed",
        trace_id=trace_id,
        at_ms=_now_ms(),
        order_id=_order_id(close_outcome.exchange_order),
        events=[event.get("event_type") for event in close_outcome.execution_events],
        execution_state_records=[asdict(record) for record in close_outcome.execution_state_records],
        criteria="close_submitted",
    )


def _run_margin_short_flow(
    exchange: BinanceExchange,
    symbol: Symbol,
    notional: Decimal,
    _stop_offset: Decimal,
    _take_profit_offset: Decimal,
    report: LiveSmokeReport,
    cfg: Config,
) -> None:
    price = _latest_price(exchange, symbol)
    _quantity_for_notional(exchange, symbol, notional, price)
    tcfg = _task_config(symbol, notional, chainer_mode="BOTH")
    router = AutoExecutionRouter(tcfg, exchange=exchange, cfg=cfg)
    trace_id = _trace_id("margin-short")
    entry = _operation(OperateType.SHORT, price)
    _attach_macd_like_metadata(
        entry,
        direction="SHORT",
        stop_price=float(price * (Decimal("1") + _stop_offset)),
        take_profit=float(price * (Decimal("1") - _take_profit_offset)),
        trace_id=trace_id,
    )

    protection_ids_before_entry: set[str] = _current_protection_order_ids(exchange, symbol)
    try:
        outcome = router.route(entry)
        _require_submitted(outcome, "margin short entry")
        _require_native_protection(outcome, "margin short entry")
        entry_verify = _verify_entry_with_protection(
            exchange=exchange,
            symbol=symbol,
            outcome=outcome,
            label="margin short entry",
            previous_protection_ids=protection_ids_before_entry,
        )
        report.add(
            "margin_short_entry",
            "passed",
            trace_id=trace_id,
            at_ms=_now_ms(),
            order_id=_order_id(outcome.exchange_order),
            native_protection=outcome.native_protection,
            events=[event.get("event_type") for event in outcome.execution_events],
            verification=entry_verify,
            execution_state_records=[asdict(record) for record in outcome.execution_state_records],
            criteria="entry+native_protection_submitted",
        )

        old_stop_protection_id = _stop_loss_order_id_from_outcome(outcome)
        protection_ids_before_replace = set(entry_verify["protection_order_ids_after"])
        risk_update = _operation(OperateType.RISK_UPDATE, price)
        replacement_stop = _safe_replacement_stop_price(
            price,
            direction="SHORT",
            fallback_offset=_stop_offset,
        )
        _attach_breakeven_update(
            risk_update,
            direction="SHORT",
            trace_id=trace_id,
            old_stop=float(price * (Decimal("1") + _stop_offset)),
            new_stop=float(replacement_stop),
            old_protection_order_id=old_stop_protection_id,
        )
        update_outcome = router.route(risk_update)
        _require_submitted(update_outcome, "margin short breakeven replace")
        replace_verify = _verify_replace_protection(
            exchange=exchange,
            symbol=symbol,
            outcome=update_outcome,
            label="margin short breakeven replace",
            protection_ids_before_replace=protection_ids_before_replace,
        )
        report.add(
            "margin_short_breakeven_replace",
            "passed",
            trace_id=trace_id,
            at_ms=_now_ms(),
            order_id=_order_id(update_outcome.exchange_order),
            old_protection_order_id=old_stop_protection_id,
            native_protection=update_outcome.native_protection,
            events=[event.get("event_type") for event in update_outcome.execution_events],
            verification=replace_verify,
            execution_state_records=[asdict(record) for record in update_outcome.execution_state_records],
            criteria="risk_update_submitted",
        )
    finally:
        _cancel_all_open_orders(exchange, symbol, report, step_prefix="margin")

    close = _operation(OperateType.CLOSE, price)
    _attach_signal_metadata(close, direction="SHORT", trace_id=trace_id)
    close_outcome = router.route(close)
    _require_submitted(close_outcome, "margin short close")
    report.add(
        "margin_short_close",
        "passed",
        trace_id=trace_id,
        at_ms=_now_ms(),
        order_id=_order_id(close_outcome.exchange_order),
        events=[event.get("event_type") for event in close_outcome.execution_events],
        execution_state_records=[asdict(record) for record in close_outcome.execution_state_records],
        criteria="close_submitted",
    )


def _task_config(symbol: Symbol, notional: Decimal, *, chainer_mode: str) -> TaskConfig:
    return TaskConfig(
        0,
        TaskType.TRADER,
        SymbolInterval(f"{symbol.base}-{symbol.quote}", Interval.INTERVAL_1m),
        strategies=["macd_triple_divergence"],
        free=float(notional),
        live_execution_mode="auto_trade",
        live_trade_max_notional=float(notional),
        strategy_params={"chainer_mode": chainer_mode},
    )


def _operation(otype: OperateType, price: Decimal) -> Operate:
    return Operate(otype, int(time.time()), float(price))


def _trace_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def _attach_macd_like_metadata(op: Operate, *, direction: str, stop_price: float, take_profit: float, trace_id: str) -> None:
    op.signal_event_id = trace_id
    op.signal_metadata = {
        "strategy": "macd_triple_divergence",
        "event_id": op.signal_event_id,
        "suggested_stop_price": stop_price,
        "trace_id": trace_id,
    }
    op.framework_trade = {
        "trade_id": op.signal_event_id,
        "direction": direction,
        "initial_stop_price": stop_price,
        "stop_price": stop_price,
        "take_profit": take_profit,
        "risk_reward_ratio": 1.0,
        "trace_id": trace_id,
    }


def _attach_breakeven_update(
    op: Operate,
    *,
    direction: str,
    trace_id: str,
    old_stop: float,
    new_stop: float,
    old_protection_order_id: str | None = None,
) -> None:
    op.signal_event_id = f"{trace_id}-be"
    op.signal_metadata = {
        "strategy": "macd_triple_divergence",
        "event_id": op.signal_event_id,
        "trace_id": trace_id,
    }
    op.framework_trade = {
        "trade_id": trace_id,
        "direction": direction,
        "stop_price": old_stop,
        "trace_id": trace_id,
    }
    if old_protection_order_id:
        op.protection_order_id = str(old_protection_order_id)
        op.framework_trade["protection_order_id"] = str(old_protection_order_id)
    op.breakeven_old_stop = old_stop
    op.breakeven_new_stop = new_stop
    op.breakeven_step = 1


def _safe_replacement_stop_price(price: Decimal, *, direction: str, fallback_offset: Decimal) -> Decimal:
    buffer = min(max(fallback_offset / Decimal("100"), Decimal("0.0005")), Decimal("0.002"))
    if str(direction).upper() == "SHORT":
        return price * (Decimal("1") + buffer)
    return price * (Decimal("1") - buffer)


def _attach_signal_metadata(op: Operate, *, direction: str, trace_id: str) -> None:
    op.signal_event_id = f"{trace_id}-{direction.lower()}-{int(time.time())}"
    op.signal_metadata = {
        "strategy": "macd_triple_divergence",
        "event_id": op.signal_event_id,
        "trace_id": trace_id,
    }


def _latest_price(exchange: BinanceExchange, symbol: Symbol) -> Decimal:
    if getattr(exchange, "spot_client", None) is None:
        klines = exchange.get_latest_klines(SymbolInterval(f"{symbol.base}-{symbol.quote}", Interval.INTERVAL_1m), 1) or []
        if not klines:
            raise RuntimeError(f"missing latest price for {symbol.name()}: no klines returned")
        return Decimal(str(klines[-1].close))
    payload = exchange.spot_client.rest_api.ticker_price(symbol=symbol.name()).data()
    price = _get(payload, "price")
    if price is None:
        raise RuntimeError(f"missing latest price for {symbol.name()}: {payload}")
    return Decimal(str(price))


def _quantity_for_notional(exchange: BinanceExchange, symbol: Symbol, notional: Decimal, price: Decimal) -> Decimal:
    info = exchange.exchange_info(symbol.name())
    step_size = _symbol_filter_value(info, "LOT_SIZE", "stepSize") or Decimal("0.000001")
    min_qty = _symbol_filter_value(info, "LOT_SIZE", "minQty") or Decimal("0")
    min_notional = _symbol_filter_value(info, "MIN_NOTIONAL", "minNotional") or Decimal("0")
    quantity = _floor_to_step(notional / price, step_size)
    if quantity <= 0 or quantity < min_qty:
        raise RuntimeError(f"computed quantity {quantity} is below minQty {min_qty}")
    if quantity * price < min_notional:
        raise RuntimeError(f"notional {quantity * price} is below exchange minNotional {min_notional}")
    return quantity


def _symbol_filter_value(info: Any, filter_type: str, field_name: str) -> Decimal | None:
    symbols = _get(info, "symbols") or []
    symbol_info = symbols[0] if symbols else info
    for item in _get(symbol_info, "filters") or []:
        if _get(item, "filterType") == filter_type:
            value = _get(item, field_name)
            return Decimal(str(value)) if value is not None else None
    return None


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def _require_submitted(outcome, label: str) -> None:
    if outcome.status != AutoExecutionStatus.SUBMITTED:
        reason = str(outcome.reason or "")
        remediation = ""
        if "MAX_NUM_ALGO_ORDERS" in reason:
            remediation = (
                " remediation=Binance rejected due to algo-order limit; clear existing stop/TP/OCO orders "
                "for the symbol in Spot and Cross Margin, then rerun verification."
            )
        raise RuntimeError(
            f"{label} failed: status={outcome.status} reason={outcome.reason}{remediation} payload={outcome.to_dict()}"
        )


def _require_native_protection(outcome, label: str) -> None:
    if not getattr(outcome, "native_protection", False):
        raise RuntimeError(f"{label} failed: native_protection not enabled payload={outcome.to_dict()}")


def _cancel_all_open_orders(exchange: BinanceExchange, symbol: Symbol, report: LiveSmokeReport, *, step_prefix: str) -> None:
    try:
        before_ids = _current_protection_order_ids(exchange, symbol)
        cancel_all = getattr(exchange, "cancel_all_open_orders", None)
        if cancel_all is None:
            raise RuntimeError("exchange does not support cancel_all_open_orders")
        payload = cancel_all(symbol)
        after_ids = _current_protection_order_ids(exchange, symbol)
        if after_ids:
            raise RuntimeError(
                f"cancel verification failed: protection orders still open after cancel, remaining={sorted(after_ids)}"
            )
        report.add(
            f"{step_prefix}_cancel_open_orders",
            "passed",
            at_ms=_now_ms(),
            canceled=_jsonable(payload),
            verification={
                "open_protection_order_ids_before": sorted(before_ids),
                "open_protection_order_ids_after": sorted(after_ids),
                "cancel_verified": True,
            },
            manual_verify=[
                f"Open Orders 页面确认 {symbol.name()} 无残留保护单",
                "若有残留，视为失败并记录 orderId",
            ],
        )
    except Exception as exc:
        report.add(f"{step_prefix}_cancel_open_orders", "failed", error=str(exc))
        raise


def _cleanup_blocking_orders_for_acceptance(
    *,
    report: LiveSmokeReport,
    symbol: Symbol,
    exchanges: list[tuple[str, Any]],
) -> dict[str, Any]:
    started_at_ms = _now_ms()
    scopes: list[dict[str, Any]] = []
    residual_ids: list[str] = []
    try:
        for label, exchange in exchanges:
            before_orders = _current_open_order_snapshots(exchange, symbol)
            before_ids = sorted(_order_snapshot_ids(before_orders))
            cancel_payload = None
            cancel_error = None
            try:
                cancel_payload = exchange.cancel_all_open_orders(symbol)
            except Exception as exc:
                cancel_error = str(exc)
            after_orders = _current_open_order_snapshots(exchange, symbol)
            after_ids = sorted(_order_snapshot_ids(after_orders))
            residual_ids.extend(f"{label}:{order_id}" for order_id in after_ids)
            scopes.append(
                {
                    "scope": label,
                    "symbol": symbol.name(),
                    "open_order_count_before": len(before_orders),
                    "open_orders_before": before_orders,
                    "open_order_ids_before": before_ids,
                    "cancel_payload": _jsonable(cancel_payload),
                    "cancel_error": cancel_error,
                    "open_order_count_after": len(after_orders),
                    "open_orders_after": after_orders,
                    "open_order_ids_after": after_ids,
                    "residual_count": len(after_ids),
                    "verified_absent": len(after_ids) == 0,
                }
            )
        evidence = {
            "started_at_ms": started_at_ms,
            "ended_at_ms": _now_ms(),
            "symbol": symbol.name(),
            "scopes": scopes,
            "final_residual_count": len(residual_ids),
            "residual_order_refs": residual_ids,
        }
        if residual_ids:
            raise RuntimeError(f"residual blocking orders remain after cleanup: {residual_ids}")
        report.add("test_000_cleanup_blocking_orders", "passed", **evidence)
        return evidence
    except Exception as exc:
        evidence = {
            "started_at_ms": started_at_ms,
            "ended_at_ms": _now_ms(),
            "symbol": symbol.name(),
            "scopes": scopes,
            "final_residual_count": len(residual_ids),
            "residual_order_refs": residual_ids,
            "error": str(exc),
        }
        report.add("test_000_cleanup_blocking_orders", "failed", **evidence)
        raise


def _list_open_orders_for_acceptance(
    *,
    report: LiveSmokeReport,
    symbol: Symbol,
    exchanges: list[tuple[str, Any]],
) -> dict[str, Any]:
    started_at_ms = _now_ms()
    scopes: list[dict[str, Any]] = []
    errors: list[str] = []
    for label, exchange in exchanges:
        try:
            orders = _current_open_order_snapshots(exchange, symbol)
            scopes.append(
                {
                    "scope": label,
                    "symbol": symbol.name(),
                    "open_order_count": len(orders),
                    "open_orders": orders,
                    "query_error": None,
                }
            )
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            scopes.append(
                {
                    "scope": label,
                    "symbol": symbol.name(),
                    "open_order_count": None,
                    "open_orders": [],
                    "query_error": str(exc),
                }
            )
    evidence = {
        "started_at_ms": started_at_ms,
        "ended_at_ms": _now_ms(),
        "symbol": symbol.name(),
        "scopes": scopes,
    }
    if errors:
        evidence["error"] = "open-order listing failed: " + " | ".join(errors)
        report.add("test_000a_list_open_orders", "failed", **evidence)
        return evidence
    report.add("test_000a_list_open_orders", "passed", **evidence)
    return evidence


def _current_open_order_snapshots(exchange: BinanceExchange, symbol: Symbol) -> list[dict[str, Any]]:
    reader = getattr(exchange, "get_open_orders", None)
    if reader is None:
        raise RuntimeError("exchange does not support get_open_orders")
    orders = reader(symbol) or []
    return [_open_order_snapshot(order) for order in orders]


def _order_snapshot_ids(orders: list[dict[str, Any]]) -> set[str]:
    return {str(order["order_id"]) for order in orders if order.get("order_id") is not None}


def _open_order_snapshot(order: Any) -> dict[str, Any]:
    payload = _object_to_dict(order)
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    order_id = (
        payload.get("id")
        or payload.get("orderId")
        or payload.get("order_id")
        or payload.get("orderId".lower())
        or info.get("orderId")
    )
    client_order_id = (
        payload.get("clientOrderId")
        or payload.get("client_order_id")
        or payload.get("clientOrderId".lower())
        or info.get("clientOrderId")
    )
    return {
        "order_id": str(order_id) if order_id is not None else None,
        "client_order_id": str(client_order_id) if client_order_id is not None else None,
        "symbol": payload.get("symbol") or info.get("symbol"),
        "side": payload.get("side") or info.get("side"),
        "type": payload.get("type") or info.get("type"),
        "status": payload.get("status") or info.get("status"),
        "amount": payload.get("amount") or payload.get("origQty") or payload.get("orig_qty") or info.get("origQty"),
        "price": payload.get("price") or info.get("price"),
        "stop_price": payload.get("stopPrice") or payload.get("stop_price") or info.get("stopPrice"),
        "time": payload.get("timestamp") or payload.get("time") or payload.get("transactTime") or info.get("time"),
        "raw": _jsonable(payload),
    }


def _object_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    payload: dict[str, Any] = {}
    for key in (
        "id",
        "orderId",
        "order_id",
        "clientOrderId",
        "client_order_id",
        "symbol",
        "side",
        "type",
        "status",
        "amount",
        "origQty",
        "orig_qty",
        "price",
        "stopPrice",
        "stop_price",
        "time",
        "timestamp",
        "transactTime",
        "info",
    ):
        if hasattr(value, key):
            payload[key] = getattr(value, key)
    return payload


def _order_id(payload: Any) -> str | None:
    if payload is None:
        return None
    if isinstance(payload, dict):
        value = payload.get("orderId") or payload.get("order_id") or payload.get("clientOrderId")
        return str(value) if value is not None else None
    value = getattr(payload, "order_id", None) or getattr(payload, "orderId", None)
    return str(value) if value is not None else None


def _get(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    actual_instance = getattr(value, "actual_instance", None)
    if actual_instance is not None and actual_instance is not value:
        nested = _get(actual_instance, name)
        if nested is not None:
            return nested
    return getattr(value, name, None)


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, list):
            return [_jsonable(item) for item in value]
        if isinstance(value, tuple):
            return [_jsonable(item) for item in value]
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if hasattr(value, "__dict__"):
            return {key: _jsonable(item) for key, item in vars(value).items() if not key.startswith("_")}
        return str(value)


def _env_decimal(name: str, default: str) -> Decimal:
    return Decimal(str(os.getenv(name, default)))


def _env_driver_type() -> ExchangeDriverType:
    raw = str(os.getenv("CHAINERTRADER_LIVE_SMOKE_DRIVER", "ccxt")).strip().lower()
    if raw in {"ccxt", ExchangeDriverType.CCXT.value}:
        return ExchangeDriverType.CCXT
    if raw in {"binance_native", "native", ExchangeDriverType.BINANCE_NATIVE.value}:
        return ExchangeDriverType.BINANCE_NATIVE
    raise RuntimeError(f"unsupported CHAINERTRADER_LIVE_SMOKE_DRIVER={raw}")


def _preflight_exchange(
    exchange: BinanceExchange,
    symbol: Symbol,
    notional: Decimal,
    *,
    require_margin: bool,
    report: LiveSmokeReport,
) -> None:
    info = exchange.exchange_info(symbol.name())
    if not info:
        raise RuntimeError(f"preflight failed: exchange_info unavailable for {symbol.name()}")
    price = _latest_price(exchange, symbol)
    qty = _quantity_for_notional(exchange, symbol, notional, price)
    open_protection_orders = []
    protection_reader = getattr(exchange, "get_open_protection_orders", None)
    if protection_reader is not None:
        open_protection_orders = protection_reader(symbol) or []
    if open_protection_orders:
        _cancel_all_open_orders(exchange, symbol, report, step_prefix="preflight")
        open_protection_orders = protection_reader(symbol) or []
    if open_protection_orders:
        _attempt_force_settlement(exchange, symbol, report, require_margin=require_margin)
        open_protection_orders = protection_reader(symbol) or []
    if open_protection_orders:
        raise RuntimeError(
            f"preflight failed: {symbol.name()} still has {len(open_protection_orders)} open protection/algo orders after auto-clean; "
            "manual exchange intervention required"
        )
    if require_margin and not exchange.is_cross_margin_ready():
        raise RuntimeError("preflight failed: cross margin is not ready")
    report.add(
        "preflight_margin" if require_margin else "preflight_spot",
        "passed",
        at_ms=_now_ms(),
        symbol=symbol.name(),
        latest_price=float(price),
        quantity=float(qty),
        open_protection_order_count=len(open_protection_orders),
        required_notional=float(notional),
        margin_ready=(exchange.is_cross_margin_ready() if require_margin else None),
        manual_verify=[
            "确认 API key 有交易权限",
            "确认账户资金足够覆盖名义金额与手续费",
            "若是 margin 流，确认 cross margin 已开通",
            "预检会自动撤销该交易对残留保护单，若失败会尝试强制收口并要求人工介入",
        ],
    )


def _attempt_force_settlement(exchange: BinanceExchange, symbol: Symbol, report: LiveSmokeReport, *, require_margin: bool) -> None:
    try:
        positions = exchange.get_position_view(symbol) or []
        if not positions:
            report.add(
                "preflight_force_settlement",
                "passed",
                at_ms=_now_ms(),
                symbol=symbol.name(),
                action="no_open_position",
            )
            return
        forced = []
        for pos in positions:
            side = str(getattr(getattr(pos, "side", None), "value", getattr(pos, "side", ""))).lower()
            qty = float(getattr(pos, "quantity", 0.0) or 0.0)
            if qty <= 0:
                continue
            if side == "long":
                payload = exchange.new_order(symbol, OperateType.SELL, qty)
                forced.append({"side": "long", "close_op": "SELL", "qty": qty, "order": _jsonable(payload)})
            elif side == "short" and require_margin:
                payload = exchange.new_margin_order(symbol, OperateType.CLOSE, qty)
                forced.append({"side": "short", "close_op": "CLOSE", "qty": qty, "order": _jsonable(payload)})
        report.add(
            "preflight_force_settlement",
            "passed",
            at_ms=_now_ms(),
            symbol=symbol.name(),
            forced_actions=forced,
        )
    except Exception as exc:
        report.add(
            "preflight_force_settlement",
            "failed",
            at_ms=_now_ms(),
            symbol=symbol.name(),
            error=str(exc),
        )


def _run_objective_with_resilience(
    *,
    report: LiveSmokeReport,
    objective_name: str,
    objective,
    remediation=None,
    hard_failures: list[str],
) -> None:
    try:
        objective()
    except Exception as exc:
        reason = str(exc)
        if _is_actionable_reason(reason):
            report.add(
                f"{objective_name}_actionable_remediation",
                "passed",
                at_ms=_now_ms(),
                reason=reason,
                classification="actionable",
                remediation="retry_after_preflight_cleanup",
            )
            if remediation is not None:
                remediation()
            try:
                objective()
                report.add(
                    f"{objective_name}_retry_after_remediation",
                    "passed",
                    at_ms=_now_ms(),
                )
                return
            except Exception as retry_exc:
                reason = str(retry_exc)
        if _is_force_majeure_reason(reason):
            probe = None
            if _is_margin_borrow_blocker_reason(reason):
                probe = _collect_margin_borrow_blocker_probe(report=report)
            report.add(
                f"{objective_name}_skipped_force_majeure",
                "skipped",
                at_ms=_now_ms(),
                reason=reason,
                policy="skip_and_continue",
                classification="force_majeure",
                blocker_probe=probe,
            )
            return
        report.add(
            f"{objective_name}_failed",
            "failed",
            at_ms=_now_ms(),
            reason=reason,
            policy="non_force_majeure_hard_fail",
        )
        hard_failures.append(f"{objective_name}: {reason}")


def _current_protection_order_ids(exchange: BinanceExchange, symbol: Symbol) -> set[str]:
    reader = getattr(exchange, "get_open_protection_orders", None)
    if reader is None:
        return set()
    orders = reader(symbol) or []
    ids: set[str] = set()
    for order in orders:
        for oid in getattr(order, "exchange_order_ids", ()) or ():
            ids.add(str(oid))
    return ids


def _event_types(outcome) -> set[str]:
    return {str(event.get("event_type")) for event in (outcome.execution_events or []) if isinstance(event, dict)}


def _verify_entry_with_protection(
    *,
    exchange: BinanceExchange,
    symbol: Symbol,
    outcome,
    label: str,
    previous_protection_ids: set[str],
) -> dict[str, Any]:
    etypes = _event_types(outcome)
    if "order_submitted" not in etypes or "order_accepted" not in etypes:
        raise RuntimeError(f"{label} verification failed: missing order_submitted/order_accepted events")
    if "protection_armed" not in etypes:
        raise RuntimeError(f"{label} verification failed: missing protection_armed event")
    expected_ids = _outcome_order_ids(outcome)
    after_ids = _current_protection_order_ids(exchange, symbol)
    verification_mode = "open_orders_snapshot"
    if not after_ids:
        if not expected_ids:
            raise RuntimeError(f"{label} verification failed: no open protection order found after entry")
        if not exchange.verify_order_ids(symbol, sorted(expected_ids)):
            raise RuntimeError(
                f"{label} verification failed: no open protection order found and verify_order_ids failed for {sorted(expected_ids)}"
            )
        verification_mode = "verify_order_ids_fallback"
        after_ids = set(expected_ids)
    return {
        "event_types": sorted(etypes),
        "verification_mode": verification_mode,
        "protection_order_ids_before": sorted(previous_protection_ids),
        "protection_order_ids_after": sorted(after_ids),
        "expected_protection_order_ids": sorted(expected_ids),
        "new_protection_order_ids": sorted(after_ids - previous_protection_ids),
    }


def _verify_replace_protection(
    *,
    exchange: BinanceExchange,
    symbol: Symbol,
    outcome,
    label: str,
    protection_ids_before_replace: set[str],
) -> dict[str, Any]:
    etypes = _event_types(outcome)
    if "protection_replaced" not in etypes:
        raise RuntimeError(f"{label} verification failed: missing protection_replaced event")
    expected_ids = _outcome_order_ids(outcome)
    after_ids = _current_protection_order_ids(exchange, symbol)
    verification_mode = "open_orders_snapshot"
    if not after_ids:
        if not expected_ids:
            raise RuntimeError(f"{label} verification failed: no open protection order after replace")
        if not exchange.verify_order_ids(symbol, sorted(expected_ids)):
            raise RuntimeError(
                f"{label} verification failed: no open protection order after replace and verify_order_ids failed for {sorted(expected_ids)}"
            )
        verification_mode = "verify_order_ids_fallback"
        after_ids = set(expected_ids)
    old_removed = protection_ids_before_replace - after_ids
    new_added = after_ids - protection_ids_before_replace
    if not old_removed and verification_mode != "verify_order_ids_fallback":
        raise RuntimeError(f"{label} verification failed: no old protection order removed")
    if not new_added:
        raise RuntimeError(f"{label} verification failed: no new protection order created")
    return {
        "event_types": sorted(etypes),
        "verification_mode": verification_mode,
        "protection_order_ids_before": sorted(protection_ids_before_replace),
        "protection_order_ids_after": sorted(after_ids),
        "expected_protection_order_ids": sorted(expected_ids),
        "removed_old_protection_order_ids": sorted(old_removed),
        "added_new_protection_order_ids": sorted(new_added),
    }


def _outcome_order_ids(outcome) -> set[str]:
    ids: set[str] = set()
    for event in (getattr(outcome, "execution_events", None) or []):
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or "")
        if event_type not in {"protection_armed", "protection_replaced"}:
            continue
        event_order_id = event.get("order_id")
        if event_order_id:
            ids.add(str(event_order_id))
        metadata = event.get("metadata")
        if isinstance(metadata, dict):
            raw_payload = metadata.get("raw_payload")
            _collect_order_ids(raw_payload, ids)
    return ids


def _stop_loss_order_id_from_outcome(outcome) -> str | None:
    for event in (getattr(outcome, "execution_events", None) or []):
        if not isinstance(event, dict):
            continue
        if str(event.get("event_type") or "") != "protection_armed":
            continue
        metadata = event.get("metadata")
        if not isinstance(metadata, dict):
            continue
        order_id = _first_order_id_by_type(metadata.get("raw_payload"), "STOP_LOSS")
        if order_id:
            return order_id
    ids = sorted(_outcome_order_ids(outcome))
    return ids[0] if ids else None


def _first_order_id_by_type(payload: Any, order_type: str) -> str | None:
    if payload is None:
        return None
    if isinstance(payload, dict):
        payload_type = str(payload.get("type") or payload.get("origType") or "").upper()
        direct_id = payload.get("orderId") or payload.get("order_id")
        if direct_id is not None and payload_type == order_type:
            return str(direct_id)
        for key in ("orders", "orderReports", "order_reports"):
            nested = payload.get(key)
            if isinstance(nested, list):
                for item in nested:
                    found = _first_order_id_by_type(item, order_type)
                    if found:
                        return found
        for value in payload.values():
            if isinstance(value, (dict, list, tuple)):
                found = _first_order_id_by_type(value, order_type)
                if found:
                    return found
        return None
    if isinstance(payload, (list, tuple)):
        for item in payload:
            found = _first_order_id_by_type(item, order_type)
            if found:
                return found
        return None
    actual_instance = getattr(payload, "actual_instance", None)
    if actual_instance is not None and actual_instance is not payload:
        return _first_order_id_by_type(actual_instance, order_type)
    return None


def _collect_order_ids(payload: Any, dest: set[str]) -> None:
    if payload is None:
        return
    if isinstance(payload, dict):
        direct_id = payload.get("orderId") or payload.get("order_id") or payload.get("clientOrderId")
        if direct_id is not None:
            dest.add(str(direct_id))
        nested = payload.get("orders")
        if isinstance(nested, list):
            for item in nested:
                _collect_order_ids(item, dest)
        for value in payload.values():
            if isinstance(value, (dict, list, tuple)):
                _collect_order_ids(value, dest)
        return
    if isinstance(payload, (list, tuple)):
        for item in payload:
            _collect_order_ids(item, dest)
        return
    actual_instance = getattr(payload, "actual_instance", None)
    if actual_instance is not None and actual_instance is not payload:
        _collect_order_ids(actual_instance, dest)


def _is_actionable_reason(reason: str) -> bool:
    text = str(reason or "").upper()
    actionable_patterns = (
        "MAX_NUM_ALGO_ORDERS",
        "OPEN_ORDERS",
        "FILTER FAILURE",
    )
    return any(item in text for item in actionable_patterns)


def _aggressive_symbol_cleanup(
    *,
    report: LiveSmokeReport,
    symbol: Symbol,
    exchanges: list[tuple[str, BinanceExchange | None]],
) -> None:
    for label, exchange in exchanges:
        if exchange is None:
            continue
        step = f"{label}_aggressive_cancel_open_orders"
        try:
            canceled = exchange.cancel_all_open_orders(symbol)
            report.add(
                step,
                "passed",
                at_ms=_now_ms(),
                symbol=symbol.name(),
                canceled=_jsonable(canceled),
            )
        except Exception as exc:
            report.add(
                step,
                "failed",
                at_ms=_now_ms(),
                symbol=symbol.name(),
                error=str(exc),
            )


def _is_force_majeure_reason(reason: str) -> bool:
    text = str(reason or "").lower()
    force_patterns = (
        "read timed out",
        "requesttimeout",
        "connectionpool",
        "network is unreachable",
        "temporary failure in name resolution",
        "api-key format invalid",
        "invalid api-key",
        "permission denied",
        "insufficient_quote_balance",
        "capital/config/getall",
        "ip banned",
        "account has insufficient balance for requested action",
        "insufficient balance",
        "this action is disabled on this account",
        "account is disabled",
        "service unavailable",
        "internal error",
        "your borrow amount has exceed maximum borrow amount",
    )
    return any(item in text for item in force_patterns)


def _is_margin_borrow_blocker_reason(reason: str) -> bool:
    text = str(reason or "").lower()
    return "-3006" in text or "borrow amount has exceed maximum borrow amount" in text


def _collect_margin_borrow_blocker_probe(*, report: LiveSmokeReport) -> dict[str, Any]:
    probe: dict[str, Any] = {
        "at_ms": _now_ms(),
        "probe_status": "collected",
        "checks": {},
        "hypothesis": "cross_margin_borrow_limit_reached_or_restricted",
        "suggested_actions": [
            "检查 Cross Margin 负债与利息，优先偿还后重试。",
            "检查可借额度（maxBorrowable）是否为 0 或不足本次下单需求。",
            "确认是否存在高风险率/账户限制导致不可借。",
        ],
    }
    symbol = os.getenv("CHAINERTRADER_LIVE_SMOKE_SYMBOL", "BTC-USDT")
    try:
        from trader.exchange.driver import ExchangeDriverType
        from trader.exchange.exchange_config import ExchangeConfig, MarginMode
        from trader.exchange.binance.exchange import BinanceExchange

        cfg = Config(cash=1.0, window=1)
        log = Logger(cfg).log()
        exchange = BinanceExchange(
            ExchangeConfig(
                api_key=os.getenv("BINANCE_API_KEY", ""),
                api_secret=os.getenv("BINANCE_API_SECRET", ""),
                margin_mode=MarginMode.CROSS_MARGIN,
                driver=_env_driver_type() if os.getenv("CHAINERTRADER_LIVE_SMOKE_DRIVER") else ExchangeDriverType.CCXT,
                base_path=os.getenv("BINANCE_MARGIN_BASE_PATH", "https://api.binance.com"),
            ),
            log,
        )
        symbol_obj = Symbol(symbol)
        probe["checks"]["symbol"] = symbol_obj.name()
        probe["checks"]["open_orders"] = _current_open_order_snapshots(exchange, symbol_obj)
        probe["checks"]["positions"] = [_jsonable(item) for item in (exchange.get_position_view(symbol_obj) or [])]
        probe["checks"]["margin_account"] = _snapshot_cross_margin_account(exchange)
        probe["checks"]["max_borrowable"] = _snapshot_max_borrowable(exchange, assets=(symbol_obj.base, symbol_obj.quote))
        report.add(
            "margin_borrow_blocker_probe",
            "passed",
            **probe,
        )
    except Exception as exc:
        probe["probe_status"] = "probe_failed"
        probe["error"] = str(exc)
        report.add(
            "margin_borrow_blocker_probe",
            "failed",
            **probe,
        )
    return probe


def _snapshot_cross_margin_account(exchange: Any) -> dict[str, Any]:
    acct = None
    try:
        if getattr(exchange, "_use_ccxt", lambda: False)():
            acct = exchange.ccxt_driver.get_account()
        else:
            manager = MarginTradingManager(exchange.cfg, exchange.log)
            acct = manager.query_cross_margin_account_details()
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
    payload = _object_to_dict(acct) if acct is not None else {}
    info = payload.get("info", {}) if isinstance(payload.get("info"), dict) else {}
    user_assets = info.get("userAssets") or payload.get("user_assets") or payload.get("userAssets") or []
    assets = []
    for row in user_assets:
        item = _object_to_dict(row)
        asset = item.get("asset")
        if not asset:
            continue
        borrowed = float(item.get("borrowed") or 0.0)
        interest = float(item.get("interest") or 0.0)
        free = float(item.get("free") or 0.0)
        net_asset = float(item.get("netAsset") or item.get("net_asset") or 0.0)
        if any(abs(v) > 0 for v in (borrowed, interest, free, net_asset)):
            assets.append(
                {
                    "asset": asset,
                    "free": free,
                    "borrowed": borrowed,
                    "interest": interest,
                    "net_asset": net_asset,
                }
            )
    assets_sorted = sorted(assets, key=lambda x: (x["borrowed"] + x["interest"]), reverse=True)
    return {
        "status": "ok",
        "margin_level": info.get("marginLevel") or payload.get("margin_level"),
        "total_liability_btc": info.get("totalLiabilityOfBtc") or payload.get("total_liability_of_btc"),
        "total_asset_btc": info.get("totalAssetOfBtc") or payload.get("total_asset_of_btc"),
        "assets_with_exposure": assets_sorted[:20],
    }


def _snapshot_max_borrowable(exchange: Any, assets: tuple[str, ...]) -> list[dict[str, Any]]:
    client = getattr(getattr(exchange, "ccxt_driver", None), "client", None)
    if client is None:
        return [{"status": "unavailable", "reason": "ccxt_client_missing"}]
    endpoints = (
        "sapiGetMarginMaxBorrowable",
        "sapi_get_margin_max_borrowable",
    )
    fn = None
    for name in endpoints:
        fn = getattr(client, name, None)
        if fn is not None:
            break
    if fn is None:
        return [{"status": "unavailable", "reason": "max_borrowable_endpoint_missing"}]
    rows: list[dict[str, Any]] = []
    for asset in assets:
        try:
            data = fn({"asset": asset})
            payload = _jsonable(data)
            rows.append(
                {
                    "asset": asset,
                    "status": "ok",
                    "amount": _extract_numeric_field(payload, ("amount", "borrowLimit", "maxBorrowable", "borrowable")),
                    "raw": payload,
                }
            )
        except Exception as exc:
            rows.append({"asset": asset, "status": "error", "error": str(exc)})
    return rows


def _extract_numeric_field(payload: Any, names: tuple[str, ...]) -> float | None:
    if isinstance(payload, dict):
        for name in names:
            if name in payload:
                try:
                    return float(payload[name])
                except Exception:
                    return None
    return None


def main() -> None:
    if os.getenv("CHAINERTRADER_LIVE_SMOKE_LIST_OPEN_ORDERS_ONLY", "0") == "1":
        report = list_open_orders_from_env()
    elif os.getenv("CHAINERTRADER_LIVE_SMOKE_CLEANUP_ONLY", "0") == "1":
        report = cleanup_blocking_orders_from_env()
    else:
        report = run_binance_live_smoke_from_env()
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
