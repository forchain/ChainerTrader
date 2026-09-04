from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from trader.exchange.exchange_config import MarginMode
from trader.strategy.strategy import parse_strategies
from trader.utils.symbol_interval import SymbolInterval

SHORT_CAPABLE_MODES = {"SHORT_ONLY", "BOTH"}


def _strategy_params(task: Any) -> dict[str, Any]:
    return dict(getattr(task, "strategy_params", {}) or {})


def _chainer_mode(task: Any) -> str:
    params = _strategy_params(task)
    raw = params.get("chainer_mode")
    if raw is None:
        return "LONG_ONLY"
    return str(raw).strip().upper()


def task_requires_short_capability(task: Any) -> bool:
    return _chainer_mode(task) in SHORT_CAPABLE_MODES


def infer_required_margin_mode(tasks: Iterable[Any]) -> MarginMode:
    for task in tasks:
        if task_requires_short_capability(task):
            return MarginMode.CROSS_MARGIN
    return MarginMode.SPOT


@dataclass
class LiveStartupSelfCheckResult:
    passed: bool
    required_margin_mode: MarginMode
    exchange_margin_mode: MarginMode | None
    exchange_connected: bool
    exchange_time_available: bool
    kline_checks: list[dict[str, Any]] = field(default_factory=list)
    strategy_checks: list[dict[str, Any]] = field(default_factory=list)
    short_capable: bool = True
    details: list[str] = field(default_factory=list)

    @property
    def klines_available(self) -> bool:
        return all(item.get("passed") for item in self.kline_checks)

    @property
    def strategies_available(self) -> bool:
        return all(item.get("passed") for item in self.strategy_checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "required_margin_mode": self.required_margin_mode.value,
            "exchange_margin_mode": self.exchange_margin_mode.value if self.exchange_margin_mode is not None else None,
            "exchange_connected": self.exchange_connected,
            "exchange_time_available": self.exchange_time_available,
            "kline_checks": list(self.kline_checks),
            "strategy_checks": list(self.strategy_checks),
            "short_capable": self.short_capable,
            "details": list(self.details),
        }

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"{status} exchange_connected={self.exchange_connected} "
            f"time={self.exchange_time_available} "
            f"required_margin_mode={self.required_margin_mode.value} "
            f"exchange_margin_mode={self.exchange_margin_mode.value if self.exchange_margin_mode else 'unknown'} "
            f"kline_checks={len(self.kline_checks)} strategy_checks={len(self.strategy_checks)} "
            f"short_capable={self.short_capable}"
        )


def evaluate_live_startup_self_check(exchange: Any, tasks: Iterable[Any], *, limit: int = 1) -> LiveStartupSelfCheckResult:
    task_list = list(tasks)
    required_margin_mode = infer_required_margin_mode(task_list)
    exchange_margin_mode = getattr(exchange, "margin_mode", None)

    exchange_connected = _check_exchange_connected(exchange)
    exchange_time_available = _check_exchange_time(exchange)
    kline_checks = _check_klines(exchange, task_list, limit=limit)
    strategy_checks = _check_strategies(task_list)
    short_capable = _check_short_capability(required_margin_mode, exchange_margin_mode)

    details = []
    if not exchange_connected:
        details.append("exchange_connection_failed")
    if not exchange_time_available:
        details.append("exchange_time_unavailable")
    if not all(item.get("passed") for item in kline_checks):
        details.append("kline_fetch_failed")
    if not all(item.get("passed") for item in strategy_checks):
        details.append("strategy_load_failed")
    if not short_capable:
        details.append("short_capability_missing")

    passed = not details
    return LiveStartupSelfCheckResult(
        passed=passed,
        required_margin_mode=required_margin_mode,
        exchange_margin_mode=exchange_margin_mode,
        exchange_connected=exchange_connected,
        exchange_time_available=exchange_time_available,
        kline_checks=kline_checks,
        strategy_checks=strategy_checks,
        short_capable=short_capable,
        details=details,
    )


def _check_exchange_connected(exchange: Any) -> bool:
    ping = getattr(exchange, "ping", None)
    if ping is None:
        return False
    try:
        return bool(ping())
    except Exception:
        return False


def _check_exchange_time(exchange: Any) -> bool:
    fetch_time = getattr(exchange, "time", None)
    if fetch_time is None:
        return False
    try:
        return fetch_time() is not None
    except Exception:
        return False


def _check_klines(exchange: Any, tasks: list[Any], *, limit: int) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for task in tasks:
        si = getattr(task, "symbol_interval", None)
        if si is None:
            continue
        key = si.name() if hasattr(si, "name") else str(si)
        if key in seen:
            continue
        seen.add(key)
        passed = False
        error = None
        candles = []
        try:
            candles = exchange.get_latest_klines(si, limit) or []
            passed = len(candles) > 0
        except Exception as exc:
            error = str(exc)
        checks.append(
            {
                "symbol_interval": key,
                "passed": passed,
                "candles": len(candles),
                "error": error,
            }
        )
    return checks


def _check_strategies(tasks: list[Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for task in tasks:
        strategies = tuple(getattr(task, "strategies", None) or ())
        if not strategies or strategies in seen:
            continue
        seen.add(strategies)
        passed = False
        error = None
        loaded = None
        try:
            loaded = parse_strategies(list(strategies))
            passed = loaded is not None
        except Exception as exc:
            error = str(exc)
        checks.append(
            {
                "strategies": list(strategies),
                "passed": passed,
                "loaded": len(loaded or []),
                "error": error,
                "chainer_mode": _chainer_mode(task),
            }
        )
    return checks


def _check_short_capability(required_margin_mode: MarginMode, exchange_margin_mode: Any) -> bool:
    if required_margin_mode == MarginMode.SPOT:
        return True
    return exchange_margin_mode == MarginMode.CROSS_MARGIN
