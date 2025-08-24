from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def exchange_info(symbol: str, request: Request):
    if len(symbol) <= 0:
        return {"error": "must config symbol"}
    return request.app.state.app.exchange.get_exchange_info(symbol)
