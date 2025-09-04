from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def time(request: Request):
    ret = {"time": request.app.state.app.exchange.time()}
    ret["offset"] = request.app.state.app.exchange.server_time_offset()

    return ret
