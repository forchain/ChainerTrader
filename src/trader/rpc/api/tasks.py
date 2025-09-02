from fastapi import APIRouter, Request

router = APIRouter()


@router.post("")
async def add_tasks(request: Request):
    raw_bytes = await request.body()
    cfg = raw_bytes.decode("utf-8")
    return request.app.state.app.send_add_tasks_msg(cfg)


@router.get("")
def get_tasks(request: Request):
    tss = request.app.state.app.task_manager.get_all_task_state()
    ret = []
    for ts in tss:
        ret.append(ts.to_dict())
    return ret
