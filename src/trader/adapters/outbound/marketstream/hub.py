"""Market stream hub: fan-out and reconnect orchestration over a connector port."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from trader.core.marketdata.interfaces import MarketStreamPort
from trader.core.marketdata.stream import MarketStreamKey, MarketStreamState, MarketStreamStatus
from trader.core.marketdata.warmup import KlineUpdate

CatchUpCallback = Callable[[MarketStreamKey], Awaitable[None]]
ReconnectCallback = Callable[[], Awaitable[None]]
MarketStreamConnector = MarketStreamPort


class MarketStreamSubscription:
    def __init__(self, hub: "MarketStreamHub", key: MarketStreamKey, queue: asyncio.Queue[KlineUpdate]):
        self._hub = hub
        self.key = key
        self.queue = queue
        self._closed = False

    async def get(self) -> KlineUpdate:
        return await self.queue.get()

    async def unsubscribe(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._hub.unsubscribe(self.key, self.queue)


@dataclass
class _StreamEntry:
    key: MarketStreamKey
    subscribers: set[asyncio.Queue]
    state: MarketStreamState = MarketStreamState.STOPPED
    last_error: str | None = None
    reconnect_callbacks: dict[asyncio.Queue, ReconnectCallback] | None = None


class MarketStreamHub:
    def __init__(
        self,
        connector: MarketStreamPort,
        catch_up: CatchUpCallback | None = None,
        *,
        reconnect_delays: tuple[float, ...] = (1.0, 5.0, 15.0, 60.0),
        reconnect_concurrency: int = 2,
    ):
        self.connector = connector
        self.catch_up = catch_up
        self.reconnect_delays = reconnect_delays or (1.0,)
        self._streams: dict[MarketStreamKey, _StreamEntry] = {}
        self._reconnect_tasks: dict[MarketStreamKey, asyncio.Task] = {}
        self._reconnect_semaphore = asyncio.Semaphore(max(1, reconnect_concurrency))
        self._lock = asyncio.Lock()

    async def subscribe(self, key: MarketStreamKey, reconnect_callback: ReconnectCallback | None = None) -> MarketStreamSubscription:
        queue: asyncio.Queue[KlineUpdate] = asyncio.Queue()
        should_start = False
        async with self._lock:
            entry = self._streams.get(key)
            if entry is None:
                entry = _StreamEntry(key=key, subscribers=set(), state=MarketStreamState.STARTING)
                self._streams[key] = entry
                should_start = True
            entry.subscribers.add(queue)
            if reconnect_callback is not None:
                if entry.reconnect_callbacks is None:
                    entry.reconnect_callbacks = {}
                entry.reconnect_callbacks[queue] = reconnect_callback

        if should_start:
            await self._start_stream(key)

        return MarketStreamSubscription(self, key, queue)

    async def unsubscribe(self, key: MarketStreamKey, queue: asyncio.Queue) -> None:
        should_stop = False
        async with self._lock:
            entry = self._streams.get(key)
            if entry is None:
                return
            entry.subscribers.discard(queue)
            if entry.reconnect_callbacks is not None:
                entry.reconnect_callbacks.pop(queue, None)
            if not entry.subscribers:
                entry.state = MarketStreamState.STOPPED
                should_stop = True
                reconnect_task = self._reconnect_tasks.pop(key, None)
            else:
                reconnect_task = None

        if should_stop:
            if reconnect_task is not None:
                reconnect_task.cancel()
            await self.connector.stop(key, reason="last subscriber unsubscribed")

    async def publish(self, key: MarketStreamKey, update: KlineUpdate) -> None:
        async with self._lock:
            subscribers = list(self._streams.get(key, _StreamEntry(key, set())).subscribers)
        for subscriber in subscribers:
            await subscriber.put(update)

    async def handle_disconnect(self, key: MarketStreamKey, reason: str = "websocket disconnected") -> None:
        async with self._lock:
            entry = self._streams.get(key)
            if entry is None:
                return
            if key in self._reconnect_tasks:
                return
            entry.state = MarketStreamState.RECONNECTING
            reconnect_callbacks = list((entry.reconnect_callbacks or {}).values())

        logging.warning("Realtime stream disconnected: key=%s reason=%s", key.stream_name(), reason)
        try:
            await self.connector.stop(key, reason=reason)
        except Exception as exc:
            async with self._lock:
                entry = self._streams.get(key)
                if entry is not None:
                    entry.last_error = str(exc)
        await self._run_reconnect_callbacks(key, reconnect_callbacks)

        async with self._lock:
            entry = self._streams.get(key)
            should_restart = entry is not None and bool(entry.subscribers)

        if should_restart and not await self._try_start_stream(key):
            await self._schedule_reconnect_retry(key)
            return

        async with self._lock:
            entry = self._streams.get(key)
            if entry is not None and entry.subscribers:
                entry.state = MarketStreamState.RUNNING

    async def _run_reconnect_callbacks(self, key: MarketStreamKey, reconnect_callbacks: list[ReconnectCallback]) -> None:
        if self.catch_up:
            await self.catch_up(key)
        for reconnect_callback in reconnect_callbacks:
            await reconnect_callback()

    async def _try_start_stream(self, key: MarketStreamKey) -> bool:
        try:
            async with self._reconnect_semaphore:
                await self._start_stream(key)
            return True
        except Exception as exc:
            async with self._lock:
                entry = self._streams.get(key)
                if entry:
                    entry.state = MarketStreamState.ERROR
                    entry.last_error = str(exc)
            logging.warning("Realtime stream restart failed for %s: %s", key.stream_name(), exc)
            return False

    async def _schedule_reconnect_retry(self, key: MarketStreamKey) -> None:
        async with self._lock:
            entry = self._streams.get(key)
            if entry is None or not entry.subscribers or key in self._reconnect_tasks:
                return
            task = asyncio.create_task(self._reconnect_until_running(key))
            self._reconnect_tasks[key] = task

    async def _reconnect_until_running(self, key: MarketStreamKey) -> None:
        try:
            attempt = 0
            while True:
                await asyncio.sleep(self.reconnect_delays[min(attempt, len(self.reconnect_delays) - 1)])
                async with self._lock:
                    entry = self._streams.get(key)
                    if entry is None or not entry.subscribers or entry.state == MarketStreamState.STOPPED:
                        return
                    entry.state = MarketStreamState.RECONNECTING
                    reconnect_callbacks = list((entry.reconnect_callbacks or {}).values())
                await self._run_reconnect_callbacks(key, reconnect_callbacks)
                if await self._try_start_stream(key):
                    async with self._lock:
                        entry = self._streams.get(key)
                        if entry is not None and entry.subscribers:
                            entry.state = MarketStreamState.RUNNING
                    return
                attempt += 1
        except asyncio.CancelledError:
            raise
        finally:
            async with self._lock:
                self._reconnect_tasks.pop(key, None)

    def status(self, key: MarketStreamKey) -> MarketStreamStatus:
        entry = self._streams.get(key)
        if entry is None:
            return MarketStreamStatus(key=key, state=MarketStreamState.STOPPED, subscriber_count=0)
        return MarketStreamStatus(key=key, state=entry.state, subscriber_count=len(entry.subscribers), last_error=entry.last_error)

    async def _start_stream(self, key: MarketStreamKey) -> None:
        async def on_update(update: KlineUpdate) -> None:
            await self.publish(key, update)

        async def on_disconnect() -> None:
            await self.handle_disconnect(key)

        try:
            await self.connector.start(key, on_update, on_disconnect)
        except Exception as exc:
            async with self._lock:
                entry = self._streams.get(key)
                if entry:
                    entry.state = MarketStreamState.ERROR
                    entry.last_error = str(exc)
            raise

        async with self._lock:
            entry = self._streams.get(key)
            if entry and entry.subscribers:
                entry.state = MarketStreamState.RUNNING
                entry.last_error = None
