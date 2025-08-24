from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def read_app_version(request: Request):
    return {"version": request.app.state.app.version()}
