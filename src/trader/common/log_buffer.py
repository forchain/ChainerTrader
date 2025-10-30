import threading
from collections import deque


class LogBuffer:
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.buffer = deque(maxlen=max_size)
        self._lock = threading.Lock()

    def add(self, msg: str):
        with self._lock:
            self.buffer.append(msg)

    def get_logs(self) -> list[str]:
        with self._lock:
            return list(self.buffer)

    def clear(self):
        with self._lock:
            self.buffer.clear()

    def size(self) -> int:
        return len(self.buffer)

    def is_empty(self) -> bool:
        return self.size() == 0
