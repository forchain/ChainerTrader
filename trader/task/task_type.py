
from enum import Enum

class TaskType(Enum):
    TRADER = 0
    BACK_TRADER = 1
    UPDATE_KLINES = 2
    CHECK_KLINES = 3
    IMPORT_CSV = 4

def parse_task_type(name):
    if name == TaskType.TRADER.name:
        return TaskType.TRADER
    elif name == TaskType.BACK_TRADER.name:
        return TaskType.BACK_TRADER
    elif name == TaskType.UPDATE_KLINES.name:
        return TaskType.UPDATE_KLINES
    elif name == TaskType.CHECK_KLINES.name:
        return TaskType.CHECK_KLINES
    elif name == TaskType.IMPORT_CSV.name:
        return TaskType.IMPORT_CSV
    return None