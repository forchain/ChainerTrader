from fastapi import APIRouter, Request

router = APIRouter()


@router.post("")
async def tasks(request: Request):
    raw_bytes = await request.body()
    cfg = raw_bytes.decode("utf-8")
    return request.app.state.app.send_add_tasks_msg(cfg)


@router.get("")
def tasks(request: Request):
    return request.app.state.app.db_manager.task.get_all_tasks()
