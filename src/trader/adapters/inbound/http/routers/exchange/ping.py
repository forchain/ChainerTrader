from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def ping(request: Request):
    return {"result": request.app.state.app.exchange.ping()}
