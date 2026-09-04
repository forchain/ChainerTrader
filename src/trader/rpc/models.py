from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

from trader.app.app import App
from trader.exchange.balance import Balance
from trader.utils.task_state import TaskStateType


class TasksInfo(BaseModel):
    total: int = 0
    completed: int = 0
    tasks: list[dict[str, Any]]


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


def get_taskinfo(app: App) -> TasksInfo:
    tss = app.task_manager.get_all_task_state()
    completed = 0
    tasks: list[dict[str, Any]] = []
    for ts in tss:
        if ts.state == TaskStateType.DONE:
            completed += 1
        tasks.append(ts.to_dict())

    # Sort tasks by start_time in descending order (newest first)
    tasks.sort(key=lambda x: x.get('start_time', ''), reverse=True)

    return TasksInfo(total=len(tss), completed=completed, tasks=tasks)


def get_accounts_info(app: App) -> AcctsInfo:
    balances = app.exchange.get_account_balances()

    return AcctsInfo(total=len(balances), balances=balances)


def get_logs_info(app: App) -> LogsInfo:
    logs = app.logger.get_buffer_str()

    return LogsInfo(total=len(logs), logs=logs)


def get_klines_info(app: App) -> KlinesInfo:
    if not app.task_manager.latest_si:
        return KlinesInfo(total=0, klines=[], name="")

    collection = app.db_manager.kline.get_collection(app.task_manager.latest_si.name())
    kls_cache = app.db_manager.kline.get_latest_klines(collection, 1000)

    klines: list[dict[str, Any]] = []
    if len(kls_cache) > 0:
        for kl in kls_cache:
            klines.append(kl.to_dict())

    return KlinesInfo(total=0, klines=klines, name=f"{app.task_manager.latest_si.name()}")
