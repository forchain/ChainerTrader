from pydantic import BaseModel


class Balance(BaseModel):
    asset: str = ""
    free: float = 0
    locked: float = 0
    max_borrowable: float = 0
    operable: float = 0
