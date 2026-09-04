from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from trader.exchange.balance import Balance
from trader.utils.task_state import TaskStateType

if TYPE_CHECKING:
    from trader.app.app import App


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


class LogsInfo(BaseModel):
    total: int = 0
    logs: list[str]


class KlinesInfo(BaseModel):
    total: int = 0
    name: str
    klines: list[dict[str, Any]]


async def get_taskinfo(app: "App", user=None, page: int = 1, per_page: int | None = None) -> TasksInfo:
    user_id = None if user is None else user.id
    tss = await app.task_manager.get_all_task_state(user_id=user_id)
    completed = 0
    tasks: list[dict[str, Any]] = []
    for ts in tss:
        if ts.state == TaskStateType.DONE:
            completed += 1
        tasks.append(ts.to_dict())

    # Sort tasks by start_time in descending order (newest first)
    tasks.sort(key=lambda x: x.get("start_time", ""), reverse=True)

    total = len(tss)
    safe_page = max(1, int(page))
    if per_page is None:
        return TasksInfo(total=total, completed=completed, tasks=tasks, page=1, per_page=total, total_pages=1)
    safe_per_page = max(1, int(per_page))
    total_pages = max(1, (total + safe_per_page - 1) // safe_per_page)
    safe_page = min(safe_page, total_pages)
    start = (safe_page - 1) * safe_per_page
    end = start + safe_per_page
    return TasksInfo(
        total=total,
        completed=completed,
        tasks=tasks[start:end],
        page=safe_page,
        per_page=safe_per_page,
        total_pages=total_pages,
    )


def get_accounts_info(app: "App") -> AcctsInfo:
    if app.exchange is None:
        return AcctsInfo(total=0, balances=[])
    balances = app.exchange.get_account_balances()

    return AcctsInfo(total=len(balances), balances=balances)


def get_logs_info(app: "App") -> LogsInfo:
    logs = app.logger.get_buffer_str()

    return LogsInfo(total=len(logs), logs=logs)


async def get_klines_info(app: "App") -> KlinesInfo:
    if not app.task_manager.latest_si:
        return KlinesInfo(total=0, klines=[], name="")

    kls_cache = await app.db_manager.kline.get_latest_klines(app.task_manager.latest_si.name(), 1000)

    klines: list[dict[str, Any]] = []
    if len(kls_cache) > 0:
        for kl in kls_cache:
            klines.append(kl.to_dict())

    return KlinesInfo(total=0, klines=klines, name=f"{app.task_manager.latest_si.name()}")
