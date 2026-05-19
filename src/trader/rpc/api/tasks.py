from fastapi import APIRouter, HTTPException, Request

from trader.auth.context import current_user
from trader.auth.credentials import service_key_available
from trader.task.task_config import parse_task_config
from trader.task.task_type import TaskType

router = APIRouter()


@router.post("")
async def add_tasks(request: Request):
    raw_bytes = await request.body()
    cfg = raw_bytes.decode("utf-8")
    user = await current_user(request)
    taskcs = parse_task_config(cfg) if cfg else []
    await _preflight_user_live_tasks(request, user, taskcs)
    return request.app.state.app.send_add_tasks_msg(cfg, user_id=None if user is None else user.id)


@router.get("")
async def get_tasks(request: Request):
    user = await current_user(request)
    user_id = None if user is None or user.is_admin else user.id
    tss = await request.app.state.app.task_manager.get_all_task_state(user_id=user_id)
    ret = []
    for ts in tss:
        ret.append(ts.to_dict())
    return ret


async def _preflight_user_live_tasks(request: Request, user, taskcs) -> None:
    if user is None or getattr(user, "is_admin", False):
        return
    if not any(taskc.ttype == TaskType.TRADER for taskc in taskcs):
        return
    cfg = getattr(request.app.state, "cfg", None)
    if not service_key_available(getattr(cfg, "secret_key", None)):
        raise HTTPException(status_code=400, detail="TRADER_SECRET_KEY is required to start user-owned live trading tasks")
    rpc_app = getattr(request.app.state, "app", None)
    db_manager = getattr(rpc_app, "db_manager", None)
    credential_repo = getattr(db_manager, "exchange_credential", None)
    if credential_repo is None:
        raise HTTPException(status_code=400, detail="live trading requires a user exchange credential store")
    credential = await credential_repo.get_default(user.id, "BINANCE")
    if credential is None:
        raise HTTPException(status_code=400, detail=f"missing BINANCE API credential for user_id={user.id}")
