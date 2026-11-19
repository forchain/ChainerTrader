from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def version(request: Request):
    return {"version": request.app.state.app.version()}
