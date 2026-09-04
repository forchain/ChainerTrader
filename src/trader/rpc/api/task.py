from fastapi import APIRouter, Request

from trader.auth.context import current_user

router = APIRouter()


@router.get("")
async def get_task(id: int, request: Request):
    user = await current_user(request)
    user_id = None if user is None or user.is_admin else user.id
    ts = await request.app.state.app.task_manager.get_task_state(id, user_id=user_id)
    if ts:
        return ts.to_dict()
    return {"id": id, "error": "invalid"}


@router.post("")
async def close_task(id: int, request: Request):
    user = await current_user(request)
    user_id = None if user is None or user.is_admin else user.id
    ret = request.app.state.app.task_manager.close_task(id, user_id=user_id)
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
