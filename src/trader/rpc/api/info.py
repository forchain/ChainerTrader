from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def read_app_info(request: Request):
    return request.app.state.app.info()
