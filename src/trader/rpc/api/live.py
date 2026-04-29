import json
import time
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from trader.live.dashboard import build_risk_overlay_events, build_signal_marker_event, notification_event, strategy_execution_event
from trader.live.monitor import build_initial_snapshot, list_live_strategy_summaries, serialize_dashboard_event
from trader.strategy.trader_result import TraderResult
from trader.utils.operate import Operate, OperateType

router = APIRouter()

LOCAL_CLIENT_HOSTS = {"127.0.0.1", "::1", "localhost"}


def is_local_request(request: Request) -> bool:
    host = getattr(getattr(request, "client", None), "host", "")
    return str(host).lower() in LOCAL_CLIENT_HOSTS


@router.get("/strategies")
def list_live_strategies(request: Request):
    return list_live_strategy_summaries(request.app.state.app.task_manager)


@router.get("/strategies/{strategy_id}/snapshot")
def live_strategy_snapshot(strategy_id: int, request: Request):
    task = request.app.state.app.task_manager.get_task(strategy_id)
    if task is None:
        raise HTTPException(status_code=404, detail="live strategy not found")
    return build_initial_snapshot(task, request.app.state.app.db_manager)


@router.get("/strategies/{strategy_id}/events")
async def live_strategy_events(strategy_id: int, request: Request):
    bus = request.app.state.live_event_bus
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
    task = app.task_manager.get_task(strategy_id)
    if task is None:
        raise HTTPException(status_code=404, detail="live strategy not found")

    op = _debug_operation(task, _latest_kline_for_task(app, task), side)
    result = _empty_result(op)
    task.process_result(result)
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
