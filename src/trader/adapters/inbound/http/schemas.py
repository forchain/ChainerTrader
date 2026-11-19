from typing import Any

from pydantic import BaseModel, Field

from trader.core.exchange.domain import Balance


class TasksInfo(BaseModel):
    total: int = 0
    completed: int = 0
    tasks: list[dict[str, Any]]
    page: int = 1
    per_page: int = 0
    total_pages: int = 1


class AcctsInfo(BaseModel):
    total: int = 0
    balances: list[Balance]
    open_orders: list[dict[str, Any]] = Field(default_factory=list)
    locked_reasons: list[dict[str, Any]] = Field(default_factory=list)
    borrow_asset: str = ""
    borrowable_amount: float = 0
    operable_amount: float = 0
    account_error: str = ""


class LogsInfo(BaseModel):
    total: int = 0
    logs: list[str]


class KlinesInfo(BaseModel):
    total: int = 0
    name: str
    klines: list[dict[str, Any]]
