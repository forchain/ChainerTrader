from fastapi import APIRouter, Request

router = APIRouter()


@router.post("")
def log_level(request: Request, level: str = "INFO"):
    request.app.state.app.logger.setLevel(level)
    return {"level": request.app.state.app.logger.get_level()}
