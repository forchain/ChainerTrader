from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def account(request: Request):
    return request.app.state.app.exchange.account()
