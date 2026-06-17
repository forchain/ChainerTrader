from math import ceil

from fastapi import APIRouter, Request

from trader.auth.context import current_user

router = APIRouter()

OPERATION_TYPE_LABELS = {
    "BUY": "买入",
    "SELL": "卖出",
    "LONG": "做多",
    "SHORT": "做空",
    "CLOSE": "平仓",
    "RISK_UPDATE": "风控更新",
    "UNKNOWN": "未知",
}


@router.get("")
async def get_task(id: int, request: Request):
    user = await current_user(request)
    user_id = None if user is None or user.is_admin else user.id
    ts = await request.app.state.app.task_manager.get_task_state(id, user_id=user_id)
    if ts:
        return ts.to_dict()
    return {"id": id, "error": "invalid"}


@router.get("/{id}/operations")
async def get_task_operations(id: int, request: Request, page: int = 1, per_page: int = 20):
    user = await current_user(request)
    user_id = None if user is None or user.is_admin else user.id
    ts = await request.app.state.app.task_manager.get_task_state(id, user_id=user_id)
    if not ts:
        return {"task_id": id, "error": "invalid", "operations": [], "total": 0, "page": 1, "per_page": per_page, "total_pages": 0}

    page = max(1, int(page or 1))
    per_page = min(100, max(1, int(per_page or 20)))
    opts = list(getattr(getattr(ts, "tret", None), "opts", []) or [])
    total = len(opts)
    total_pages = ceil(total / per_page) if total else 0
    if total_pages:
        page = min(page, total_pages)
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "task_id": id,
        "operations": [_operation_payload(op, start + index + 1) for index, op in enumerate(opts[start:end])],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


def _operation_payload(op, sequence: int) -> dict:
    payload = op.to_dict() if hasattr(op, "to_dict") else dict(op)
    operation_type = str(payload.get("type") or payload.get("otype") or "UNKNOWN")
    payload["sequence"] = sequence
    payload["type"] = operation_type
    payload["type_label"] = OPERATION_TYPE_LABELS.get(operation_type, operation_type or "未知")
    return payload


@router.post("")
async def close_task(id: int, request: Request):
    user = await current_user(request)
    user_id = None if user is None or user.is_admin else user.id
    task_manager = request.app.state.app.task_manager
    close_task_state = getattr(task_manager, "close_task_state", None)
    if callable(close_task_state):
        ret = await close_task_state(id, user_id=user_id)
    else:
        ret = task_manager.close_task(id, user_id=user_id)
    if ret:
        return {"id": id, "result": ret}
    else:
        return {"id": id, "result": ret, "error": f"task({id}) is not in running state"}


@router.delete("")
async def del_task(id: int, request: Request):
    user = await current_user(request)
    user_id = None if user is None or user.is_admin else user.id
    ret = request.app.state.app.task_manager.del_task(id, user_id=user_id)
    if ret:
        return {"id": id, "result": ret}
    else:
        return {"id": id, "result": ret, "error": f"task({id}) is not found"}
