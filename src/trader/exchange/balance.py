from pydantic import BaseModel


class Balance(BaseModel):
    asset: str = ""
    free: float = 0
    locked: float = 0
