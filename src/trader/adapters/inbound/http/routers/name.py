from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def name(request: Request):
    return {"name": request.app.state.app.name()}
