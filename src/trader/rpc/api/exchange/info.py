from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def info(request: Request, symbol: str = None):
    return request.app.state.app.exchange.exchange_info(symbol)
