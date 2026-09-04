import json
import inspect
import time
from datetime import datetime
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from trader.auth.context import current_user
from trader.rpc.api.tasks import _enforce_current_user_ownership, _preflight_single_running_task_per_user, _preflight_user_live_tasks
from trader.task.persisted_live_config_migration import sanitize_public_task_config_json
from trader.task.task_config import apply_persisted_task_runtime_metadata, parse_task_config
from trader.live.dashboard import build_risk_overlay_events, build_signal_marker_event, notification_event, strategy_execution_event
from trader.live.dashboard import kline_to_chart_candle
from trader.live.monitor import build_initial_snapshot, list_live_strategy_summaries, serialize_dashboard_event
from trader.common.message import new_add_tasks_msg
from trader.live.monitor import build_snapshot_overlays, parameter_fingerprint, parameter_summary
from trader.task.task_type import TaskType
from trader.strategy.trader_result import TraderResult
from trader.utils.operate import Operate, OperateType
from trader.utils.symbol_interval import Interval, SymbolInterval
from trader.utils.task_state import TaskStateType

router = APIRouter()

LOCAL_CLIENT_HOSTS = {"127.0.0.1", "::1", "localhost"}
QUOTE_ASSETS = ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI", "USD1", "USDE", "USDS", "PYUSD", "BTC", "ETH")


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def is_local_request(request: Request) -> bool:
    host = getattr(getattr(request, "client", None), "host", "")
    return str(host).lower() in LOCAL_CLIENT_HOSTS


def _can_access_task(user, task) -> bool:
    if user is None or user.is_admin:
        return True
    return getattr(getattr(task, "tcfg", None), "user_id", None) == user.id


def _task_type_name_from_state(ts) -> str:
    try:
        config = json.loads(getattr(ts, "config_json", "") or "[]")
        if isinstance(config, list) and config and isinstance(config[0], dict):
            raw = str(config[0].get("task_type") or "").strip().upper()
            if raw:
                return raw
    except Exception:
        pass
    name = str(getattr(ts, "name", "") or "")
    parts = name.split(".")
    if len(parts) >= 2 and parts[1]:
        return parts[1].upper()
    return "UNKNOWN"


def _task_config_value(ts, key: str) -> Any:
    try:
        config = json.loads(getattr(ts, "config_json", "") or "[]")
        if isinstance(config, list) and config and isinstance(config[0], dict):
            return config[0].get(key)
    except Exception:
        return None
    return None


def _task_config_dict(ts) -> dict[str, Any]:
    try:
        config = json.loads(getattr(ts, "config_json", "") or "[]")
        if isinstance(config, list) and config and isinstance(config[0], dict):
            return dict(config[0])
    except Exception:
        return {}
    return {}


def _normalize_task_config_symbol(symbol: Any) -> str:
    text = str(symbol or "").strip().upper().replace("/", "-")
    if not text or "-" in text:
        return text
    for quote in QUOTE_ASSETS:
        if text.endswith(quote) and len(text) > len(quote):
            return f"{text[:-len(quote)]}-{quote}"
    return text


def _task_name_symbol_interval(ts) -> tuple[str | None, str | None]:
    name = str(getattr(ts, "name", "") or "")
    parts = name.split(".")
    if len(parts) < 3 or not parts[2]:
        return None, None
    symbol_interval = parts[2]
    for interval in sorted((item.value for item in Interval), key=len, reverse=True):
        suffix = f"-{interval}"
        if symbol_interval.endswith(suffix):
            symbol = symbol_interval[: -len(suffix)]
            return _normalize_task_config_symbol(symbol), interval
    return None, None


def _is_parseable_task_config_symbol(symbol: Any) -> bool:
    text = str(symbol or "").strip()
    if not text or "-" not in text:
        return False
    base, quote = text.split("-", 1)
    return bool(base and quote)


def _reusable_task_config_dict(ts) -> dict[str, Any]:
    cfg = _task_config_dict(ts)
    name_symbol, name_interval = _task_name_symbol_interval(ts)
    if "symbol" in cfg:
        cfg["symbol"] = _normalize_task_config_symbol(cfg.get("symbol"))
    if not _is_parseable_task_config_symbol(cfg.get("symbol")) and name_symbol:
        cfg["symbol"] = name_symbol
    if not str(cfg.get("interval") or "").strip() and name_interval:
        cfg["interval"] = name_interval
    if "symbols" in cfg:
        raw_symbols = cfg.get("symbols") or []
        if isinstance(raw_symbols, str):
            symbol_items = raw_symbols.split(",")
        else:
            symbol_items = raw_symbols
        normalized_symbols = [_normalize_task_config_symbol(item) for item in symbol_items if str(item).strip()]
        if normalized_symbols and not _is_parseable_task_config_symbol(cfg.get("symbol")):
            cfg["symbols"] = ",".join(normalized_symbols)
        else:
            cfg.pop("symbols", None)
    cfg.pop("run_id", None)
    cfg.pop("task_batch_id", None)
    cfg.pop("id", None)
    return cfg


def _rerun_config_json(config_json: str) -> str:
    parsed = json.loads(config_json)
    if not isinstance(parsed, list):
        return config_json
    sanitized = []
    for item in parsed:
        if not isinstance(item, dict):
            sanitized.append(item)
            continue
        cfg = dict(item)
        cfg.pop("run_id", None)
        cfg.pop("task_batch_id", None)
        cfg.pop("id", None)
        sanitized.append(cfg)
    return json.dumps(sanitized, ensure_ascii=False)


def _run_id_from_state(ts) -> str | None:
    raw = _task_config_value(ts, "run_id")
    if raw in (None, ""):
        raw = _task_config_value(ts, "task_batch_id")
    text = str(raw or "").strip()
    return text or None


def _task_symbol_interval_from_state(ts) -> SymbolInterval | None:
    config = _task_config_dict(ts)
    symbol = str(config.get("symbol") or "").strip()
    interval = str(config.get("interval") or "").strip()
    if not symbol or not interval:
        return None
    try:
        normalized_symbol = symbol if "-" in symbol else f"{symbol[:-4]}-{symbol[-4:]}" if len(symbol) > 4 else symbol
        return SymbolInterval(normalized_symbol, Interval(interval))
    except ValueError:
        return None


def _task_strategy_name_from_state(ts) -> str:
    config = _task_config_dict(ts)
    if config.get("strategy"):
        return str(config["strategy"])
    if config.get("strategies"):
        return str(config["strategies"])
    return "unknown"


def _task_strategy_params_from_state(ts) -> dict[str, Any]:
    params = _task_config_value(ts, "strategy_params")
    return dict(params) if isinstance(params, dict) else {}


def _task_symbol_from_state(ts) -> str:
    symbol_interval = _task_symbol_interval_from_state(ts)
    if symbol_interval is not None:
        return symbol_interval.symbol()
    symbol = str(_task_config_value(ts, "symbol") or "").strip()
    if symbol:
        return symbol
    name = str(getattr(ts, "name", "") or "")
    parts = name.split(".")
    if len(parts) >= 3 and "-" in parts[2]:
        return parts[2].split("-", 1)[0]
    return symbol


def _task_interval_from_state(ts) -> str:
    symbol_interval = _task_symbol_interval_from_state(ts)
    if symbol_interval is not None:
        return symbol_interval.interval.value
    interval = str(_task_config_value(ts, "interval") or "").strip()
    if interval:
        return interval
    name = str(getattr(ts, "name", "") or "")
    parts = name.split(".")
    if len(parts) >= 3 and "-" in parts[2]:
        return parts[2].split("-", 1)[1]
    return interval


def _build_task_item(ts, *, is_running: bool) -> dict[str, Any]:
    return {
        "task_id": int(getattr(ts, "id", 0) or 0),
        "name": str(getattr(ts, "name", "") or ""),
        "state": str(getattr(getattr(ts, "state", None), "name", "") or ""),
        "task_type": _task_type_name_from_state(ts),
        "symbol": _task_symbol_from_state(ts),
        "interval": _task_interval_from_state(ts),
        "strategy": _task_strategy_name_from_state(ts),
        "run_id": _run_id_from_state(ts),
        "start_time": str(getattr(ts, "start_time", "") or ""),
        "strategy_end_time": str(getattr(ts, "strategy_end_time", "") or ""),
        "is_running": bool(is_running),
    }


def _renderer_kind(task_type: str) -> str:
    if task_type == TaskType.TRADER.name:
        return "live"
    if task_type == TaskType.BACK_TRADER.name:
        return "backtest"
    if task_type in {TaskType.UPDATE_KLINES.name, TaskType.CHECK_KLINES.name, TaskType.IMPORT_CSV.name, TaskType.CHECK_KLINES_NUM.name}:
        return "data"
    return "generic"


def _sort_task_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (item.get("start_time", ""), int(item.get("task_id", 0))), reverse=True)


def _annotate_run_ordinals(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        run_id = str(item.get("run_id") or "").strip()
        if not run_id:
            continue
        groups.setdefault(run_id, []).append(item)
    for _run_id, grouped in groups.items():
        ordered = sorted(grouped, key=lambda item: int(item.get("task_id", 0)))
        total = len(ordered)
        for idx, item in enumerate(ordered, start=1):
            item["run_index"] = idx
            item["run_total"] = total
    return items


def _done_sort_key(ts) -> tuple[str, str, int]:
    # Prefer finish time for DONE fallback; fall back to start_time then task id.
    return (
        str(getattr(ts, "strategy_end_time", "") or ""),
        str(getattr(ts, "start_time", "") or ""),
        int(getattr(ts, "id", 0) or 0),
    )


def _result_summary(ts) -> dict[str, Any] | None:
    result = getattr(ts, "tret", None)
    if result is None:
        return None
    keys = (
        "total_return_rate",
        "max_drawdown",
        "volatility",
        "win_rate",
        "plr",
        "avg_profit",
        "avg_loss",
        "buys",
        "sells",
        "hold_rate",
        "data_len",
    )
    return {key: getattr(result, key) for key in keys if hasattr(result, key)}


async def _build_historical_chart_snapshot(ts, db_manager, *, limit: int) -> dict[str, Any]:
    task_id = int(getattr(ts, "id", 0) or 0)
    task_type = _task_type_name_from_state(ts)
    symbol_interval = _task_symbol_interval_from_state(ts)
    params = _task_strategy_params_from_state(ts)
    candles = []
    if symbol_interval is not None and db_manager is not None and getattr(db_manager, "kline", None) is not None:
        start_time = int(getattr(ts, "strategy_start_time", 0) or 0)
        end_time = int(getattr(ts, "strategy_end_time", 0) or 0)
        if start_time > 0 or end_time > 0:
            candles = await _maybe_await(db_manager.kline.get_klines(symbol_interval.name(), start_time, end_time)) or []
        else:
            candles = await _maybe_await(db_manager.kline.get_latest_klines(symbol_interval.name(), limit)) or []
        candles = candles[-limit:]

    pseudo_task = type(
        "HistoricalTask",
        (),
        {
            "tcfg": type(
                "HistoricalTaskConfig",
                (),
                {
                    "id": task_id,
                    "ttype": getattr(TaskType, task_type, TaskType.BACK_TRADER),
                    "symbol_interval": symbol_interval,
                    "strategy_params": params,
                    "param_id": _task_config_value(ts, "param_id"),
                    "live_execution_mode": "historical",
                    "live_trade_max_notional": float(_task_config_value(ts, "live_trade_max_notional") or 0.0),
                    "requires_short_capability": bool(_task_config_value(ts, "requires_short_capability")),
                    "strategy_name": lambda self=None: _task_strategy_name_from_state(ts),
                },
            )(),
            "ts": ts,
            "name": lambda self=None: str(getattr(ts, "name", "") or ""),
        },
    )()
    overlays = await build_snapshot_overlays(pseudo_task, db_manager, candles)
    loaded = len(candles)
    snapshot = {
        "strategy_id": task_id,
        "task_id": task_id,
        "task_type": task_type,
        "state": str(getattr(getattr(ts, "state", None), "name", "") or ""),
        "name": str(getattr(ts, "name", "") or ""),
        "start_time": str(getattr(ts, "start_time", "") or ""),
        "runtime_status": {
            "state": str(getattr(getattr(ts, "state", None), "name", "") or ""),
            "task_type": task_type,
            "task_id": task_id,
        },
        "config_json": sanitize_public_task_config_json(getattr(ts, "config_json", None)),
        "market": symbol_interval.symbol() if symbol_interval is not None else "",
        "interval": symbol_interval.interval.value if symbol_interval is not None else "",
        "strategy_name": _task_strategy_name_from_state(ts),
        "execution_mode": "historical",
        "candles": [kline_to_chart_candle(kline) for kline in candles],
        "enabled_overlays": ["signals", "risk", "strategy_events"],
        "overlays": overlays,
        "history_window": {
            "limit": limit,
            "loaded": loaded,
            "insufficient": loaded < limit,
        },
        "strategy_params": params,
        "parameter_fingerprint": parameter_fingerprint(params),
        "parameter_summary": parameter_summary(params),
        "result_summary": _result_summary(ts),
    }
    if _task_config_value(ts, "param_id"):
        snapshot["param_id"] = _task_config_value(ts, "param_id")
    return snapshot


@router.get("/current-task")
async def current_task_workspace(request: Request, task_id: int | None = None):
    rpc_app = request.app.state.app
    user = await current_user(request)
    user_id = None if user is None or user.is_admin else user.id
    states = await rpc_app.task_manager.get_all_task_state(user_id=user_id)
    running = [ts for ts in states if getattr(ts, "state", None) == TaskStateType.RUNNING]
    done = [ts for ts in states if getattr(ts, "state", None) == TaskStateType.DONE]
    running_sorted = sorted(running, key=lambda ts: (str(getattr(ts, "start_time", "") or ""), int(getattr(ts, "id", 0) or 0)), reverse=True)
    done_sorted = sorted(done, key=_done_sort_key, reverse=True)
    latest_finished = done_sorted[0] if done_sorted else None

    if not running_sorted and latest_finished is None:
        return {
            "selected_task_id": None,
            "display_context": "empty",
            "running_task_id": None,
            "tasks": [],
            "renderer": "generic",
            "snapshot": None,
        }

    requested = None
    if task_id is not None:
        requested = next((ts for ts in states if int(getattr(ts, "id", 0) or 0) == task_id), None)

    if requested is not None:
        requested_run_id = _run_id_from_state(requested)
        requested_is_running = getattr(requested, "state", None) == TaskStateType.RUNNING
        if requested_run_id:
            visible_states = [
                ts
                for ts in states
                if _run_id_from_state(ts) == requested_run_id
                and (not requested_is_running or getattr(ts, "state", None) == TaskStateType.RUNNING)
            ]
            visible_states = sorted(
                visible_states,
                key=lambda ts: (str(getattr(ts, "start_time", "") or ""), int(getattr(ts, "id", 0) or 0)),
                reverse=True,
            )
        else:
            visible_states = [requested]
        display_context = "active_running_task" if requested_is_running else "historical_selection"
    elif running_sorted:
        latest_running = running_sorted[0]
        latest_running_run_id = _run_id_from_state(latest_running)
        if latest_running_run_id:
            # Active view is scoped to the latest run, not every running task in history.
            visible_states = [
                ts
                for ts in states
                if _run_id_from_state(ts) == latest_running_run_id and getattr(ts, "state", None) == TaskStateType.RUNNING
            ]
            visible_states = sorted(
                visible_states,
                key=lambda ts: (str(getattr(ts, "start_time", "") or ""), int(getattr(ts, "id", 0) or 0)),
                reverse=True,
            )
        else:
            visible_states = [latest_running]
        display_context = "active_running_task"
    else:
        latest_finished_run_id = _run_id_from_state(latest_finished)
        if latest_finished_run_id:
            visible_states = [ts for ts in states if _run_id_from_state(ts) == latest_finished_run_id]
            visible_states = sorted(
                visible_states,
                key=lambda ts: (str(getattr(ts, "start_time", "") or ""), int(getattr(ts, "id", 0) or 0)),
                reverse=True,
            )
        else:
            visible_states = [latest_finished]
        display_context = "latest_finished_task"

    by_visible_id = {int(getattr(ts, "id", 0) or 0): ts for ts in visible_states}
    selected = requested if requested is not None else None
    if selected is None:
        selected = by_visible_id.get(task_id) if task_id is not None else None
    if selected is None:
        selected = visible_states[0]

    selected_item = _build_task_item(selected, is_running=(getattr(selected, "state", None) == TaskStateType.RUNNING))
    visible_items = _annotate_run_ordinals(_sort_task_items(
        [_build_task_item(ts, is_running=(getattr(ts, "state", None) == TaskStateType.RUNNING)) for ts in visible_states]
    ))
    running_task_id = int(getattr(running_sorted[0], "id", 0) or 0) if running_sorted else None

    renderer = _renderer_kind(selected_item["task_type"])
    snapshot: dict[str, Any] = {
        "task_id": selected_item["task_id"],
        "task_type": selected_item["task_type"],
        "state": selected_item["state"],
        "name": selected_item["name"],
        "start_time": selected_item["start_time"],
        "runtime_status": {"state": selected_item["state"]},
        "config_json": sanitize_public_task_config_json(getattr(selected, "config_json", None)),
    }
    can_stream = False
    if renderer == "live":
        task = rpc_app.task_manager.get_task(selected_item["task_id"])
        # Guard against stale/wrong in-memory mapping: selected list id must match runtime task id.
        if task is not None and int(getattr(getattr(task, "tcfg", None), "id", 0) or 0) != selected_item["task_id"]:
            task = None
        cfg = getattr(rpc_app, "cfg", None)
        limit = max(1, int(getattr(cfg, "warmup_candles", 500) or 500))
        if task is not None:
            snapshot = await build_initial_snapshot(task, rpc_app.db_manager, limit=limit)
            can_stream = True
            snapshot["state"] = selected_item["state"]
            snapshot["task_type"] = selected_item["task_type"]
            snapshot["name"] = selected_item["name"]
            snapshot["start_time"] = selected_item["start_time"]
        else:
            snapshot = await _build_historical_chart_snapshot(selected, rpc_app.db_manager, limit=limit)
    elif renderer == "backtest":
        cfg = getattr(rpc_app, "cfg", None)
        limit = max(1, int(getattr(cfg, "warmup_candles", 500) or 500))
        snapshot = await _build_historical_chart_snapshot(selected, rpc_app.db_manager, limit=limit)

    return {
        "selected_task_id": selected_item["task_id"],
        "display_context": display_context,
        "running_task_id": running_task_id,
        "tasks": visible_items,
        "renderer": renderer,
        "can_stream": can_stream,
        "snapshot": snapshot,
    }


@router.post("/tasks/{task_id}/rerun")
async def rerun_task(request: Request, task_id: int):
    user = await current_user(request)
    rpc_app = request.app.state.app
    user_id = None if user is None or user.is_admin else user.id
    states = await rpc_app.task_manager.get_all_task_state(user_id=user_id)
    selected = next((ts for ts in states if int(getattr(ts, "id", 0) or 0) == task_id), None)
    if selected is None:
        raise HTTPException(status_code=404, detail=f"task({task_id}) not found")
    config_json = getattr(selected, "config_json", None)
    if not config_json:
        raise HTTPException(status_code=400, detail=f"task({task_id}) has no reusable config")
    try:
        saved_config = _task_config_dict(selected)
        taskcs = parse_task_config(_rerun_config_json(config_json))
        if not taskcs:
            # Fallback for legacy/atypical saved config_json payloads: rebuild from task state config.
            fallback_cfg = _reusable_task_config_dict(selected)
            if fallback_cfg:
                taskcs = parse_task_config(json.dumps([fallback_cfg], ensure_ascii=False))
        if not taskcs:
            fallback_cfg = _reusable_task_config_dict(selected)
            keys = ",".join(sorted(fallback_cfg.keys())) if fallback_cfg else "none"
            raise HTTPException(
                status_code=400,
                detail=(
                    f"task({task_id}) has invalid or empty reusable config "
                    f"(task_type={fallback_cfg.get('task_type')}, symbol={fallback_cfg.get('symbol')}, "
                    f"interval={fallback_cfg.get('interval')}, keys={keys})"
                ),
            )
        for tc in taskcs:
            apply_persisted_task_runtime_metadata(tc, saved_config)
        if user is not None:
            _enforce_current_user_ownership(taskcs, user.id)
            # Rerun semantics: force-stop current running tasks first, then submit rerun.
            user_states = await rpc_app.task_manager.get_all_task_state(user_id=user.id)
            running_ids = [int(getattr(ts, "id", 0) or 0) for ts in user_states if getattr(getattr(ts, "state", None), "name", None) == "RUNNING"]
            for running_id in running_ids:
                close_task_state = getattr(rpc_app.task_manager, "close_task_state", None)
                if callable(close_task_state):
                    await close_task_state(running_id, user_id=user.id)
                else:
                    rpc_app.task_manager.close_task(running_id, user_id=user.id)
            await _preflight_user_live_tasks(request, user, taskcs)
        # Avoid immediate auto-finish on rerun caused by historical end_time persisted in saved config_json.
        now_ts = int(datetime.now().timestamp())
        for tc in taskcs:
            if getattr(tc, "ttype", None) == TaskType.TRADER and int(getattr(tc, "end_time", 0) or 0) <= now_ts:
                tc.end_time = 0
        # Submit parsed task configs directly to avoid second-pass string parsing ambiguity.
        rpc_app.queue.put_nowait(new_add_tasks_msg(taskcs))
        result = {"result": "success", "tasks": [tc.to_dict() for tc in taskcs]}
    except HTTPException:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid saved task config: {exc}") from exc
    if result.get("result") != "success":
        raise HTTPException(status_code=400, detail=result.get("error") or "task manager rejected the task config")
    return result


@router.get("/strategies")
async def list_live_strategies(request: Request):
    user = await current_user(request)
    task_manager = request.app.state.app.task_manager
    summaries = list_live_strategy_summaries(task_manager)
    if user is None or user.is_admin:
        return summaries
    visible = []
    for summary in summaries:
        task = task_manager.get_task(summary["strategy_id"])
        if task is not None and _can_access_task(user, task):
            visible.append(summary)
    return visible


@router.get("/strategies/{strategy_id}/snapshot")
async def live_strategy_snapshot(strategy_id: int, request: Request):
    app = request.app.state.app
    user = await current_user(request)
    task_manager = app.task_manager
    if hasattr(task_manager, "get_task"):
        task = task_manager.get_task(strategy_id)
    else:
        task = (getattr(task_manager, "tasks", {}) or {}).get(strategy_id)
    if task is None or not _can_access_task(user, task):
        raise HTTPException(status_code=404, detail="live strategy not found")
    cfg = getattr(app, "cfg", None)
    limit = max(1, int(getattr(cfg, "warmup_candles", 500) or 500))
    return await build_initial_snapshot(task, app.db_manager, limit=limit)


@router.get("/strategies/{strategy_id}/events")
async def live_strategy_events(strategy_id: int, request: Request):
    app = getattr(request.app.state, "app", None) or request.app
    user = await current_user(request)
    task_manager = getattr(app, "task_manager", None)
    task = None
    if task_manager is not None:
        if hasattr(task_manager, "get_task"):
            task = task_manager.get_task(strategy_id)
        else:
            task = (getattr(task_manager, "tasks", {}) or {}).get(strategy_id)
        if task is None or not _can_access_task(user, task):
            raise HTTPException(status_code=404, detail="live strategy not found")
    bus = getattr(request.app.state, "live_event_bus", None) or getattr(app, "live_event_bus", None)
    if bus is None:
        raise HTTPException(status_code=404, detail="live strategy not found")
    subscription = await bus.subscribe(strategy_id)

    async def event_stream():
        try:
            while True:
                event = await subscription.get()
                yield f"data: {json.dumps(serialize_dashboard_event(event), ensure_ascii=False)}\n\n"
        finally:
            await subscription.unsubscribe()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _empty_result(op: Operate) -> TraderResult:
    return TraderResult(0.0, 0.0, timedelta(0), 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, [op], 0.0, 0)


def _latest_kline_for_task(app, task):
    db_manager = getattr(app, "db_manager", None)
    kline_store = getattr(db_manager, "kline", None) if db_manager is not None else None
    if kline_store is None:
        return None
    try:
        klines = kline_store.get_latest_klines(task.tcfg.symbol_interval.name(), 1) or []
    except AttributeError:
        return None
    return klines[-1] if klines else None


def _debug_operation(task, kline, side: str) -> Operate:
    now = int(time.time())
    if kline is not None:
        dtime = int(getattr(kline, "open_time", now))
        price = float(getattr(kline, "close", 0.0) or 0.0)
        low = float(getattr(kline, "low", price) or price)
        high = float(getattr(kline, "high", price) or price)
    else:
        dtime = now
        price = 1.0
        low = price
        high = price

    if side == "exit":
        op = Operate(OperateType.CLOSE, dtime, price)
        op.trigger_reason = "debug_manual_exit"
    else:
        op = Operate(OperateType.LONG, dtime, price)
        op.trigger_reason = "debug_manual_entry"
        params = dict(getattr(task.tcfg, "strategy_params", {}) or {})
        stop_price = low if low < price else price * 0.99
        op.stop_loss = float(stop_price)
        rr = float(params.get("chainer_risk_reward_ratio", 0.0) or 0.0)
        op.risk_reward_ratio = rr
        if rr > 0.0:
            op.take_profit = price + (price - stop_price) * rr
        op.signal_metadata = {
            "signal_event_id": f"debug-{task.tcfg.id}-{dtime}-{side}",
            "signal_type": "debug_manual_entry",
            "suggested_stop_price": float(stop_price),
            "key_kline_low": low,
            "key_kline_high": high,
        }
        op.signal_event_id = op.signal_metadata["signal_event_id"]
    return op


async def dispatch_debug_manual_signal(request: Request, strategy_id: int, side: str) -> dict:
    if not is_local_request(request):
        raise HTTPException(status_code=404, detail="debug endpoints are available only from local access")
    app = request.app.state.app
    user = await current_user(request)
    task = app.task_manager.get_task(strategy_id)
    if task is None or not _can_access_task(user, task):
        raise HTTPException(status_code=404, detail="live strategy not found")

    op = _debug_operation(task, _latest_kline_for_task(app, task), side)
    result = _empty_result(op)
    await task.process_result(result)
    notifications = task.handle_manual_trade_notifications(result)
    sent = []
    for event in notifications:
        sent.extend(app.notify_mgr.send_manual_trade_notification(event))

    bus = request.app.state.live_event_bus
    event_time = int(op.dtime)
    await bus.publish(strategy_execution_event(task.tcfg.id, event_time, result, [op]))
    await bus.publish(build_signal_marker_event(task.tcfg.id, op, getattr(task.tcfg, "live_execution_mode", "manual_notify")))
    for risk_event in build_risk_overlay_events(task.tcfg.id, op):
        await bus.publish(risk_event)
    await bus.publish(notification_event(task.tcfg.id, event_time, notifications))

    return {
        "ok": bool(notifications) and (not sent or all(item["ok"] for item in sent)),
        "side": side,
        "operation": op.to_dict(),
        "notifications": [event.to_dict() for event in notifications],
        "sent": sent,
    }


@router.post("/strategies/{strategy_id}/debug/manual-entry")
async def live_debug_manual_entry(strategy_id: int, request: Request):
    return await dispatch_debug_manual_signal(request, strategy_id, "entry")


@router.post("/strategies/{strategy_id}/debug/manual-exit")
async def live_debug_manual_exit(strategy_id: int, request: Request):
    return await dispatch_debug_manual_signal(request, strategy_id, "exit")
