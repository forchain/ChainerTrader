from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def account_commission(request: Request, symbol: str = None):
    return request.app.state.app.exchange.account_commission(symbol)
