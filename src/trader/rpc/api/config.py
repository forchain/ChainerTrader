from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def config(request: Request):
    return request.app.state.app.cfg.safe_to_dict()
