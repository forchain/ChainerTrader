from fastapi import APIRouter, Request

from trader.adapters.inbound.http.dependencies import request_user_exchange

router = APIRouter()


@router.get("")
async def account_commission(request: Request, symbol: str = None):
    exchange = await request_user_exchange(request)
    return exchange.account_commission(symbol)
