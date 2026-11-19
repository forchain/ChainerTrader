from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class LogLevelRequest(BaseModel):
    level: str


@router.get("")
def get_log_level(request: Request):
    return {"level": request.app.state.app.logger.get_level()}


@router.post("")
def set_log_level(request: Request, log_level_request: LogLevelRequest):
    request.app.state.app.logger.setLevel(log_level_request.level)
    return {"level": request.app.state.app.logger.get_level()}
