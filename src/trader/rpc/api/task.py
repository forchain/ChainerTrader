from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def get_task(id: int, request: Request):
    ts = request.app.state.app.task_manager.get_task_state(id)
    if ts:
        return ts.to_dict()
    return {"id": id, "error": "invalid"}


@router.delete("")
def del_task(id: int, request: Request):
    ret = request.app.state.app.task_manager.close_task(id)
    return {"id": id, "result": ret}
