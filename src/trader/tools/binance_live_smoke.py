from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Any

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

    @property
    def passed(self) -> bool:
        return all(step.status in {"passed", "skipped"} for step in self.steps)

    def add(self, name: str, status: str, **details: Any) -> None:
        self.steps.append(LiveSmokeStep(name=name, status=status, details=details))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload


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
    driver = _env_driver_type()
    stop_offset = _env_decimal("CHAINERTRADER_LIVE_SMOKE_STOP_OFFSET", "0.05")
    take_profit_offset = _env_decimal("CHAINERTRADER_LIVE_SMOKE_TAKE_PROFIT_OFFSET", "0.05")

    cfg = Config(cash=float(max_notional), window=500)
    log = Logger(cfg).log()
    report = LiveSmokeReport(symbol=symbol.name(), notional=float(max_notional), spot_enabled=run_spot, margin_enabled=run_margin)

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
        _run_margin_short_flow(margin_exchange, symbol, max_notional, stop_offset, take_profit_offset, report, cfg)
    else:
        report.add("margin_short_flow", "skipped", reason="set CHAINERTRADER_LIVE_SMOKE_ENABLE_MARGIN=1 to test cross-margin short")

    if run_spot:
        exchange = BinanceExchange(
            ExchangeConfig(api_key=api_key, api_secret=api_secret, margin_mode=MarginMode.SPOT, driver=driver),
            log,
        )
        _run_spot_long_flow(exchange, symbol, max_notional, stop_offset, take_profit_offset, report, cfg)
    else:
        report.add("spot_long_flow", "skipped", reason="CHAINERTRADER_LIVE_SMOKE_ENABLE_SPOT is not 1")

    return report


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
    entry = _operation(OperateType.BUY, price)
    _attach_signal_metadata(entry, direction="LONG")

    try:
        outcome = router.route(entry)
        _require_submitted(outcome, "spot long entry")
        report.add(
            "spot_long_entry",
            "passed",
            quantity=float(quantity),
            order_id=_order_id(outcome.exchange_order),
            native_protection=outcome.native_protection,
            events=[event.get("event_type") for event in outcome.execution_events],
        )
    finally:
        _cancel_all_open_orders(exchange, symbol, report, step_prefix="spot")

    close = _operation(OperateType.SELL, price)
    _attach_signal_metadata(close, direction="LONG")
    close_outcome = router.route(close)
    _require_submitted(close_outcome, "spot long close")
    report.add("spot_long_close", "passed", order_id=_order_id(close_outcome.exchange_order))


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
    entry = _operation(OperateType.SHORT, price)
    _attach_signal_metadata(entry, direction="SHORT")

    try:
        outcome = router.route(entry)
        _require_submitted(outcome, "margin short entry")
        report.add(
            "margin_short_entry",
            "passed",
            order_id=_order_id(outcome.exchange_order),
            native_protection=outcome.native_protection,
            events=[event.get("event_type") for event in outcome.execution_events],
        )
    finally:
        _cancel_all_open_orders(exchange, symbol, report, step_prefix="margin")

    close = _operation(OperateType.CLOSE, price)
    _attach_signal_metadata(close, direction="SHORT")
    close_outcome = router.route(close)
    _require_submitted(close_outcome, "margin short close")
    report.add("margin_short_close", "passed", order_id=_order_id(close_outcome.exchange_order))


def _task_config(symbol: Symbol, notional: Decimal, *, chainer_mode: str) -> TaskConfig:
    return TaskConfig(
        0,
        TaskType.TRADER,
        SymbolInterval(f"{symbol.base}-{symbol.quote}", Interval.INTERVAL_1m),
        strategies=["macd_triple_divergence"],
        free=float(notional),
        live_execution_mode="small_live_auto",
        live_trade_max_notional=float(notional),
        strategy_params={"chainer_mode": chainer_mode},
    )


def _operation(otype: OperateType, price: Decimal) -> Operate:
    return Operate(otype, int(time.time()), float(price))


def _attach_macd_like_metadata(op: Operate, *, direction: str, stop_price: float, take_profit: float) -> None:
    op.signal_event_id = f"live-smoke-{direction.lower()}-{int(time.time())}"
    op.signal_metadata = {
        "strategy": "macd_triple_divergence",
        "event_id": op.signal_event_id,
        "suggested_stop_price": stop_price,
    }
    op.framework_trade = {
        "trade_id": op.signal_event_id,
        "direction": direction,
        "initial_stop_price": stop_price,
        "stop_price": stop_price,
        "take_profit": take_profit,
        "risk_reward_ratio": 1.0,
    }


def _attach_signal_metadata(op: Operate, *, direction: str) -> None:
    op.signal_event_id = f"live-smoke-{direction.lower()}-{int(time.time())}"
    op.signal_metadata = {
        "strategy": "macd_triple_divergence",
        "event_id": op.signal_event_id,
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
        raise RuntimeError(f"{label} failed: status={outcome.status} reason={outcome.reason} payload={outcome.to_dict()}")


def _first_protection_order_id(outcome) -> str | None:
    for record in getattr(outcome, "execution_state_records", []) or []:
        if getattr(record, "protection_id", None):
            return str(record.protection_id).split(",")[0]
    for event in getattr(outcome, "execution_events", []) or []:
        if event.get("event_type") == "protection_armed" and event.get("order_id"):
            return str(event["order_id"]).split(",")[0]
    return None


def _cancel_all_open_orders(exchange: BinanceExchange, symbol: Symbol, report: LiveSmokeReport, *, step_prefix: str) -> None:
    try:
        cancel_all = getattr(exchange, "cancel_all_open_orders", None)
        if cancel_all is None:
            raise RuntimeError("exchange does not support cancel_all_open_orders")
        payload = cancel_all(symbol)
        report.add(f"{step_prefix}_cancel_open_orders", "passed", canceled=_jsonable(payload))
    except Exception as exc:
        report.add(f"{step_prefix}_cancel_open_orders", "failed", error=str(exc))
        raise


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


def main() -> None:
    report = run_binance_live_smoke_from_env()
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
