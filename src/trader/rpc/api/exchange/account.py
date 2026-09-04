from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def get_account(request: Request):
    return request.app.state.app.exchange.get_account()
