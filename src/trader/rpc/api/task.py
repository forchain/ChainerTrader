from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def task(id: int, request: Request):
    return request.app.state.app.db_manager.task.get_task(id)


@router.delete("")
def task(id: int, request: Request):
    ret = request.app.state.app.task_manager.close_task(id)
    return {"id": id, "result": ret}
