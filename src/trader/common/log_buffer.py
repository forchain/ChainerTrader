import logging
import threading
from collections import deque
from datetime import datetime
from typing import List, Dict, Any


class LogBuffer:
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.buffer = deque(maxlen=max_size)
        self._lock = threading.Lock()

    def add_log(self, record: logging.LogRecord):
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "filename": record.filename,
            "lineno": record.lineno,
            "funcName": record.funcName,
            "thread": record.thread,
            "threadName": record.threadName,
        }

        with self._lock:
            self.buffer.append(log_entry)

    def get_logs(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.buffer)

    def get_logs_as_string(self) -> List[str]:
        logs = self.get_logs()
        return [f"[{log['timestamp']}] {log['level']}:{log['name']} {log['message']}" for log in logs]

    def clear(self):
        with self._lock:
            self.buffer.clear()

    def size(self) -> int:
        return len(self.buffer)

    def is_empty(self) -> bool:
        return len(self.buffer) == 0


class LogBufferHandler(logging.Handler):
    def __init__(self, log_buffer: LogBuffer):
        super().__init__()
        self.log_buffer = log_buffer

    def emit(self, record: logging.LogRecord):
        try:
            self.log_buffer.add_log(record)
        except Exception:
            self.handleError(record)
