from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def task(id: int, request: Request):
    return request.app.state.app.db_manager.task.get_task(id)


@router.delete("")
def task(id: int, request: Request):
    pass
