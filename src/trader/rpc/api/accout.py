from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def accout(request: Request):
    return request.app.state.app.exchange.get_account()
