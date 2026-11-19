"""In-memory pub/sub bus for live dashboard events."""

from __future__ import annotations

import asyncio

from trader.core.task.dashboard import DashboardEvent


class LiveEventSubscription:
    def __init__(self, bus: "LiveEventBus", strategy_id: int, queue: asyncio.Queue):
        self.bus = bus
        self.strategy_id = strategy_id
        self.queue = queue
        self._closed = False

    async def get(self) -> DashboardEvent:
        return await self.queue.get()

    async def unsubscribe(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.bus.unsubscribe(self.strategy_id, self.queue)


class LiveEventBus:
    def __init__(self):
        self._subscribers: dict[int, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, strategy_id: int) -> LiveEventSubscription:
        queue: asyncio.Queue[DashboardEvent] = asyncio.Queue()
        async with self._lock:
            self._subscribers.setdefault(int(strategy_id), set()).add(queue)
        return LiveEventSubscription(self, int(strategy_id), queue)

    async def unsubscribe(self, strategy_id: int, queue: asyncio.Queue) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(int(strategy_id))
            if not subscribers:
                return
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(int(strategy_id), None)

    async def publish(self, event: DashboardEvent) -> None:
        async with self._lock:
            subscribers = list(self._subscribers.get(int(event.strategy_id), set()))
        for queue in subscribers:
            await queue.put(event)
