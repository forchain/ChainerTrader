from __future__ import annotations

from datetime import UTC, datetime
from logging import Logger

from tortoise import connections

from trader.database.models import TaskStateModel
from trader.utils.task_state import DATETIME_FORMART, PRIMARY_KEY, TaskState, parse_task_state


def _is_missing_error_message_column(exc: Exception) -> bool:
    text = str(exc).lower()
    return "error_message" in text and ("no such column" in text or "unknown column" in text)


def _normalize_start_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value


async def _legacy_upsert_task_without_error_message(task_id: int, values: dict) -> None:
    connection = connections.get("default")
    columns = [
        "task_id",
        "user_id",
        "state",
        "name",
        "start_time",
        "commission",
        "strategy_start_time",
        "strategy_end_time",
        "initial_cash",
        "config_json",
        "tret",
    ]
    payload = {"task_id": task_id, **values}
    column_list = ",".join([f'"{column}"' for column in columns])
    placeholders = ",".join(["?"] * len(columns))
    update_clause = ",".join([f'"{column}"=excluded."{column}"' for column in columns if column != "task_id"])
    sql = (
        f'INSERT INTO "tasks" ({column_list}) '
        f"VALUES ({placeholders}) "
        f'ON CONFLICT("task_id") DO UPDATE SET {update_clause}'
    )
    await connection.execute_query(sql, [payload.get(column) for column in columns])


def model_to_task_state(row: TaskStateModel) -> TaskState:
    payload = {
        PRIMARY_KEY: row.task_id,
        "state": row.state,
        "name": row.name,
        "start_time": row.start_time.strftime(DATETIME_FORMART),
        "commission": row.commission,
        "initial_cash": row.initial_cash,
        "config_json": row.config_json,
        "error_message": getattr(row, "error_message", None),
        "tret": row.tret,
        "user_id": row.user_id,
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
                defaults = {
                    "state": ta.state.name,
                    "user_id": ta.user_id,
                    "name": ta.name,
                    "start_time": _normalize_start_time(ta.start_time),
                    "commission": ta.commission,
                    "strategy_start_time": ta.strategy_start_time,
                    "strategy_end_time": ta.strategy_end_time,
                    "initial_cash": ta.initial_cash,
                    "config_json": ta.config_json,
                    "tret": ta.tret.to_dict() if ta.tret else None,
                }
                fields_map = getattr(getattr(TaskStateModel, "_meta", None), "fields_map", {})
                if "error_message" in fields_map:
                    defaults["error_message"] = ta.error_message
                try:
                    updated = await TaskStateModel.filter(task_id=ta.id).update(**defaults)
                    if updated == 0:
                        await TaskStateModel.create(task_id=ta.id, **defaults)
                except Exception as exc:
                    if "error_message" not in defaults or not _is_missing_error_message_column(exc):
                        raise
                    self.log.warning("tasks.error_message column is missing; run database migrations")
                    legacy_defaults = {key: value for key, value in defaults.items() if key != "error_message"}
                    updated = await TaskStateModel.filter(task_id=ta.id).update(**legacy_defaults)
                    if updated == 0:
                        await _legacy_upsert_task_without_error_message(ta.id, legacy_defaults)
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

    async def get_task_for_user(self, id: int, user_id: int) -> TaskState | None:
        row = await TaskStateModel.filter(task_id=id, user_id=user_id).first()
        if row is None:
            return None
        return model_to_task_state(row)

    async def get_all_tasks(self) -> list[TaskState]:
        rows = await TaskStateModel.all().order_by("task_id")
        return [model_to_task_state(row) for row in rows]

    async def get_all_tasks_for_user(self, user_id: int) -> list[TaskState]:
        rows = await TaskStateModel.filter(user_id=user_id).order_by("task_id")
        return [model_to_task_state(row) for row in rows]
