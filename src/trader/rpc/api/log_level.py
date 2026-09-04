from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def get_log_level(request: Request):
    return {"level": request.app.state.app.logger.get_level()}


@router.post("")
def set_log_level(request: Request, level: str = "INFO"):
    request.app.state.app.logger.setLevel(level)
    return {"level": request.app.state.app.logger.get_level()}
