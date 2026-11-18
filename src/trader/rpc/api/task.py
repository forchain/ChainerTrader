import inspect

from fastapi import APIRouter, Request

from trader.auth.context import current_user
from trader.core.task.exceptions import TaskNotFound, TaskOwnership
from trader.core.task.use_cases import GetTask, TaskScope, paginate
from trader.rpc.task_state_payload import public_task_state_dict

router = APIRouter()


async def _resolve_user(request: Request):
    composition = getattr(request.app.state, "composition", None)
    resolver = getattr(composition, "current_user_resolver", None)
    if callable(resolver):
        res = resolver(request)
        return await res if inspect.isawaitable(res) else res
    return await current_user(request)

OPERATION_TYPE_LABELS = {
    "BUY": "买入",
    "SELL": "卖出",
    "LONG": "做多",
    "SHORT": "做空",
    "CLOSE": "平仓",
    "RISK_UPDATE": "风控更新",
    "UNKNOWN": "未知",
}


async def _visible_task(request: Request, id: int, user):
    try:
        return await GetTask(request.app.state.app.task_manager).execute(id, TaskScope.for_actor(user))
    except (TaskNotFound, TaskOwnership):
        return None


@router.get("")
async def get_task(id: int, request: Request):
    user = await _resolve_user(request)
    ts = await _visible_task(request, id, user)
    if ts:
        return public_task_state_dict(ts)
    return {"id": id, "error": "invalid"}


@router.get("/{id}/operations")
async def get_task_operations(id: int, request: Request, page: int = 1, per_page: int = 20):
    user = await _resolve_user(request)
    ts = await _visible_task(request, id, user)
    if not ts:
        return {"task_id": id, "error": "invalid", "operations": [], "total": 0, "page": 1, "per_page": per_page, "total_pages": 0}

    opts = list(getattr(getattr(ts, "tret", None), "opts", []) or [])
    if not opts:
        return {
            "task_id": id,
            "operations": [],
            "total": 0,
            "page": 1,
            "per_page": min(100, max(1, int(per_page or 20))),
            "total_pages": 0,
        }
    page_result = paginate(opts, page=page, per_page=per_page, max_per_page=100)
    start = (page_result.page - 1) * page_result.per_page
    return {
        "task_id": id,
        "operations": [_operation_payload(op, start + index + 1) for index, op in enumerate(page_result.items)],
        "total": page_result.total,
        "page": page_result.page,
        "per_page": page_result.per_page,
        "total_pages": page_result.total_pages,
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
    user = await _resolve_user(request)
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
    user = await _resolve_user(request)
    user_id = None if user is None or user.is_admin else user.id
    ret = request.app.state.app.task_manager.del_task(id, user_id=user_id)
    if ret:
        return {"id": id, "result": ret}
    else:
        return {"id": id, "result": ret, "error": f"task({id}) is not found"}
