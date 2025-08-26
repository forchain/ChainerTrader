from logging import Logger
from pymongo.synchronous.collection import Collection
from trader.database.collection import get_name_for_tasks
from pymongo import ASCENDING, DESCENDING

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
        insert_data = []
        duplicate = True
        total = 0
        for ta in tasks:
            tad = ta.get_digest()
            if duplicate:
                try:
                    col.insert_one(tad)
                except Exception as e:
                    self.log.error(e)
                    duplicate = True
                else:
                    duplicate = False
                    total += 1
                finally:
                    continue

            insert_data.append(tad)

        if len(insert_data) > 0:
            col.insert_many(insert_data)
            total += len(insert_data)
        self.log.debug(f"add tasks, total:{total}")
        return total

    def get_task(self, id: int) -> TaskState | None:
        col = self.get_collection()

        result = col.find_one({PRIMARY_KEY: id})
        if result is None:
            return None
        ts = parse_task_state(result)
        self.log.debug(f"get task({result['_id']}):{ts.to_json()}")
        return ts
