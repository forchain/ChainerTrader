from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def ping(request: Request):
    pass