from __future__ import annotations

from datetime import datetime
from logging import Logger

from trader.database.models import TaskStateModel
from trader.utils.task_state import DATETIME_FORMART, PRIMARY_KEY, TaskState, parse_task_state


def model_to_task_state(row: TaskStateModel) -> TaskState:
    payload = {
        PRIMARY_KEY: row.task_id,
        "state": row.state,
        "name": row.name,
        "start_time": row.start_time.strftime(DATETIME_FORMART),
        "commission": row.commission,
        "initial_cash": row.initial_cash,
        "config_json": row.config_json,
        "tret": row.tret,
    }
    if row.strategy_start_time > 0:
        payload["strategy_start_time"] = datetime.fromtimestamp(row.strategy_start_time).strftime(DATETIME_FORMART)
    if row.strategy_end_time > 0:
        payload["strategy_end_time"] = datetime.fromtimestamp(row.strategy_end_time).strftime(DATETIME_FORMART)
    return parse_task_state(payload)


class TaskCol:
    def __init__(self, log: Logger):
        self.log = log

    async def add_tasks(self, tasks: list[TaskState]) -> int:
        if len(tasks) <= 0:
            return 0

        total = 0
        for ta in tasks:
            try:
                await TaskStateModel.update_or_create(
                    task_id=ta.id,
                    defaults={
                        "state": ta.state.name,
                        "name": ta.name,
                        "start_time": ta.start_time,
                        "commission": ta.commission,
                        "strategy_start_time": ta.strategy_start_time,
                        "strategy_end_time": ta.strategy_end_time,
                        "initial_cash": ta.initial_cash,
                        "config_json": ta.config_json,
                        "tret": ta.tret.to_dict() if ta.tret else None,
                    },
                )
            except Exception as exc:
                self.log.error(exc)
            else:
                total += 1

        self.log.debug(f"add tasks, total:{total}")
        return total

    async def del_task(self, id: int) -> bool:
        try:
            deleted_count = await TaskStateModel.filter(task_id=id).delete()
            if deleted_count != 1:
                self.log.error(f"Can't find task-{id}")
                return False
        except Exception as exc:
            self.log.error(exc)
            return False

        self.log.debug(f"del task, id:{id}")
        return True

    async def get_task(self, id: int) -> TaskState | None:
        row = await TaskStateModel.filter(task_id=id).first()
        if row is None:
            return None
        ts = model_to_task_state(row)
        self.log.debug(f"get task({row.task_id}):{ts.to_json()}")
        return ts

    async def get_all_tasks(self) -> list[TaskState]:
        rows = await TaskStateModel.all().order_by("task_id")
        return [model_to_task_state(row) for row in rows]
