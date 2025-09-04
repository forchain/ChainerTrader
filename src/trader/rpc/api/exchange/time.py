from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
def time(request: Request):
    pass
