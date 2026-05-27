import json
import re
import time
from datetime import timedelta
from enum import Enum

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from trader.auth.context import current_user
from trader.live.dashboard import build_risk_overlay_events, build_signal_marker_event, notification_event, strategy_execution_event
from trader.live.monitor import build_initial_snapshot, list_live_strategy_summaries, serialize_dashboard_event
from trader.strategy.trader_result import TraderResult
from trader.utils.operate import Operate, OperateType

router = APIRouter()

LOCAL_CLIENT_HOSTS = {"127.0.0.1", "::1", "localhost"}


def is_local_request(request: Request) -> bool:
    host = getattr(getattr(request, "client", None), "host", "")
    return str(host).lower() in LOCAL_CLIENT_HOSTS


def _can_access_task(user, task) -> bool:
    if user is None or user.is_admin:
        return True
    return getattr(getattr(task, "tcfg", None), "user_id", None) == user.id


def _extract_task_type(config_json: str | None) -> str:
    if not config_json:
        return "UNKNOWN"
    try:
        payload = json.loads(config_json)
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return str(payload[0].get("task_type", "UNKNOWN")).upper()
    except Exception:
        return "UNKNOWN"
    return "UNKNOWN"


def _task_state_name(state) -> str:
    if isinstance(state, Enum):
        return state.name
    return str(getattr(state, "name", state or "UNKNOWN"))


def _monitor_mode_for_task_type(task_type: str) -> str:
    return "live" if str(task_type).upper() == "TRADER" else "historical"


def _normalize_symbol_text(value: str) -> str:
    text = str(value or "").strip().upper()
    if "-" in text:
        return text
    match = re.match(r"^([A-Z0-9]+)(USDT|USDC|BUSD|BTC|ETH)$", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return text


def _normalize_rerun_config_json(config_json: str, user_id: int) -> str:
    payload = json.loads(config_json)
    if not isinstance(payload, list):
        raise ValueError("rerun config must be a JSON array")
    normalized = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("rerun config item must be an object")
        current = dict(item)
        current["user_id"] = user_id
        if "symbol" in current:
            current["symbol"] = _normalize_symbol_text(current.get("symbol", ""))
        normalized.append(current)
    return json.dumps(normalized, ensure_ascii=False)


def _monitor_task_item(ts, running_task) -> dict:
    if hasattr(ts, "to_dict"):
        raw = ts.to_dict()
    else:
        fallback_task_id = int(
            getattr(getattr(running_task, "tcfg", None), "id", 0) or getattr(ts, "id", 0) or 0
        )
        raw = {
            "task_id": fallback_task_id,
            "state": _task_state_name(getattr(ts, "state", None)),
            "name": f"{fallback_task_id}.{_task_state_name(getattr(ts, 'state', None))}",
            "config_json": getattr(getattr(running_task, "ts", None), "config_json", None),
            "start_time": getattr(ts, "start_time", None),
        }
    task_type = "UNKNOWN"
    if running_task is not None:
        task_type = str(getattr(getattr(running_task, "tcfg", None), "ttype", None).name if getattr(getattr(running_task, "tcfg", None), "ttype", None) else "UNKNOWN")
    if task_type == "UNKNOWN":
        task_type = _extract_task_type(raw.get("config_json"))
    state_name = _task_state_name(getattr(ts, "state", None))
    return {
        "task_id": int(raw.get("task_id") or getattr(ts, "id", 0)),
        "name": raw.get("name", ""),
        "state": state_name,
        "task_type": task_type,
        "monitor_mode": _monitor_mode_for_task_type(task_type),
        "start_time": raw.get("start_time"),
        "config_json": raw.get("config_json"),
        "can_stop": state_name == "RUNNING",
        "can_rerun": state_name == "DONE" and bool(raw.get("config_json")),
    }


@router.get("/tasks")
async def list_monitor_tasks(request: Request):
    user = await current_user(request)
    rpc_app = request.app.state.app
    user_id = None if user is None or user.is_admin else user.id
    tss = await rpc_app.task_manager.get_all_task_state(user_id=user_id)
    items = []
    for ts in tss:
        task_id = int(getattr(ts, "id", 0) or 0)
        running_task = rpc_app.task_manager.get_task(task_id) if hasattr(rpc_app.task_manager, "get_task") else None
        if running_task is None and hasattr(rpc_app.task_manager, "tasks"):
            for rid, task in (getattr(rpc_app.task_manager, "tasks", {}) or {}).items():
                if getattr(task, "ts", None) is ts:
                    task_id = int(rid or 0)
                    running_task = task
                    break
        items.append(_monitor_task_item(ts, running_task))
    items.sort(
        key=lambda item: (item.get("state") == "RUNNING", item.get("start_time") or "", item["task_id"]),
        reverse=True,
    )
    logger = getattr(rpc_app, "logger", None)
    if logger is not None:
        logger.info(f"Live monitor tasks listed: user_id={user_id} count={len(items)}")
    return items


@router.post("/tasks/{task_id}/rerun")
async def live_monitor_task_rerun(task_id: int, request: Request):
    user = await current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    user_id = None if user.is_admin else user.id
    rpc_app = request.app.state.app
    logger = getattr(rpc_app, "logger", None)
    ts = await rpc_app.task_manager.get_task_state(task_id, user_id=user_id)
    if ts is None:
        if logger is not None:
            logger.error(f"Live monitor rerun failed: user_id={user.id} task_id={task_id} detail=task not found")
        raise HTTPException(status_code=404, detail="task not found")
    state_name = _task_state_name(getattr(ts, "state", None))
    if state_name != "DONE":
        if logger is not None:
            logger.error(f"Live monitor rerun failed: user_id={user.id} task_id={task_id} detail=task state is {state_name}")
        raise HTTPException(status_code=409, detail=f"task({task_id}) is not in DONE state")
    config_json = getattr(ts, "config_json", None)
    if not config_json:
        if logger is not None:
            logger.error(f"Live monitor rerun failed: user_id={user.id} task_id={task_id} detail=missing config_json")
        raise HTTPException(status_code=400, detail=f"task({task_id}) has no replayable config_json")
    try:
        normalized_cfg = _normalize_rerun_config_json(config_json, user.id)
    except Exception as exc:
        if logger is not None:
            logger.error(f"Live monitor rerun failed: user_id={user.id} task_id={task_id} detail=invalid config_json: {exc}")
        raise HTTPException(status_code=400, detail=f"task({task_id}) has invalid config_json: {exc}") from exc
    result = rpc_app.send_add_tasks_msg(normalized_cfg, user_id=user.id)
    if result.get("result") != "success":
        detail = result.get("error") or "task manager rejected rerun config"
        if logger is not None:
            logger.error(f"Live monitor rerun failed: user_id={user.id} task_id={task_id} detail={detail}")
        raise HTTPException(status_code=400, detail=detail)
    if logger is not None:
        logger.info(f"Live monitor rerun accepted: user_id={user.id} task_id={task_id}")
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
    limit = max(1, int(getattr(cfg, "live_warmup_candles", 500) or 500))
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
