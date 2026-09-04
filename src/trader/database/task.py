from logging import Logger

from pymongo import ASCENDING
from pymongo.synchronous.collection import Collection

from trader.database.collection import get_name_for_tasks
from trader.utils.task_state import PRIMARY_KEY, TaskState, parse_task_state


class TaskCol:
    def __init__(self, db, log: Logger):
        self.db = db
        self.log = log

    def get_collection(self) -> Collection:
        collection_name = get_name_for_tasks()
        if collection_name in self.db.list_collection_names():
            return self.db[collection_name]
        else:
            self.log.info(f"Create collection {collection_name} and index")
            col = self.db[collection_name]
            col.create_index([(PRIMARY_KEY, ASCENDING)], unique=True)
            return col

    def add_tasks(self, tasks: list[TaskState]) -> int:
        col = self.get_collection()

        if len(tasks) <= 0:
            return 0
        total = 0
        for ta in tasks:
            tad = ta.to_dict()
            try:
                col.replace_one({"_id": ta.id}, tad, upsert=True)
            except Exception as e:
                self.log.error(e)
            else:
                total += 1
            finally:
                continue

        self.log.debug(f"add tasks, total:{total}")
        return total

    def del_task(self, id: int) -> bool:
        col = self.get_collection()
        try:
            result = col.delete_one({"_id": id})
            if result.deleted_count != 1:
                self.log.error(f"Can't find task-{id}")
                return False

        except Exception as e:
            self.log.error(e)
            return False

        self.log.debug(f"del task, id:{id}")
        return True

    def get_task(self, id: int) -> TaskState | None:
        col = self.get_collection()

        result = col.find_one({PRIMARY_KEY: id})
        if result is None:
            return None
        ts = parse_task_state(result)
        self.log.debug(f"get task({result['_id']}):{ts.to_json()}")
        return ts

    def get_all_tasks(self) -> list[TaskState]:
        col = self.get_collection()
        results = col.find().sort(PRIMARY_KEY, ASCENDING)
        if results is None:
            return None

        ts: list[TaskState] = []
        for ret in results:
            ts.append(parse_task_state(ret))
        return ts
