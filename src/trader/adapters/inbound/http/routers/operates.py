from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def operates(request: Request):
    return request.app.state.app.stat.get_operates()
