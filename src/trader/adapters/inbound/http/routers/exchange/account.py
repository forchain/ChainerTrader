from fastapi import APIRouter, Request

from trader.adapters.inbound.http.dependencies import request_user_exchange

router = APIRouter()


@router.get("")
async def get_account(request: Request):
    exchange = await request_user_exchange(request)
    return exchange.get_account()
