from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Protocol

from trader.live.market_data import KlineUpdate, normalize_binance_kline_message

UpdateCallback = Callable[[KlineUpdate], Awaitable[None]]
DisconnectCallback = Callable[[], Awaitable[None]]
CatchUpCallback = Callable[["MarketStreamKey"], Awaitable[None]]
ReconnectCallback = Callable[[], Awaitable[None]]

BINANCE_SPOT_WS_STREAM_URL = "wss://stream.binance.com:443/stream"


@dataclass(frozen=True)
class MarketStreamKey:
    exchange: str
    symbol: str
    interval: str

    def stream_name(self) -> str:
        return f"{self.symbol.lower()}@kline_{self.interval}"


class MarketStreamState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass(frozen=True)
class MarketStreamStatus:
    key: MarketStreamKey
    state: MarketStreamState
    subscriber_count: int
    last_error: str | None = None


class MarketStreamConnector(Protocol):
    async def start(self, key: MarketStreamKey, on_update: UpdateCallback, on_disconnect: DisconnectCallback | None = None) -> None:
        ...

    async def stop(self, key: MarketStreamKey) -> None:
        ...


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
    def __init__(self, connector: MarketStreamConnector, catch_up: CatchUpCallback | None = None):
        self.connector = connector
        self.catch_up = catch_up
        self._streams: dict[MarketStreamKey, _StreamEntry] = {}
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

        if should_stop:
            await self.connector.stop(key)

    async def publish(self, key: MarketStreamKey, update: KlineUpdate) -> None:
        async with self._lock:
            subscribers = list(self._streams.get(key, _StreamEntry(key, set())).subscribers)
        for subscriber in subscribers:
            await subscriber.put(update)

    async def handle_disconnect(self, key: MarketStreamKey) -> None:
        async with self._lock:
            entry = self._streams.get(key)
            if entry is None:
                return
            entry.state = MarketStreamState.RECONNECTING
            reconnect_callbacks = list((entry.reconnect_callbacks or {}).values())

        await self.connector.stop(key)
        if self.catch_up:
            await self.catch_up(key)
        for reconnect_callback in reconnect_callbacks:
            await reconnect_callback()

        async with self._lock:
            entry = self._streams.get(key)
            should_restart = entry is not None and bool(entry.subscribers)

        if should_restart:
            await self._start_stream(key)

        async with self._lock:
            entry = self._streams.get(key)
            if entry is not None and entry.subscribers:
                entry.state = MarketStreamState.RUNNING

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


class BinanceKlineWebSocketAdapter:
    def __init__(self, *, stream_url: str | None = None):
        self.stream_url = stream_url
        self._handles = {}

    async def start(self, key: MarketStreamKey, on_update: UpdateCallback, on_disconnect: DisconnectCallback | None = None) -> None:
        from binance_common.configuration import ConfigurationWebSocketStreams
        from binance_sdk_spot import Spot
        config = ConfigurationWebSocketStreams(stream_url=self.stream_url or BINANCE_SPOT_WS_STREAM_URL)
        client = Spot(config_ws_streams=config)
        await client.websocket_streams.create_connection()
        handle = await client.websocket_streams.kline(symbol=key.symbol.lower(), interval=key.interval)

        def on_message(message) -> None:
            update = normalize_binance_kline_message(message, exchange=key.exchange)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(on_update(update))
            except RuntimeError:
                asyncio.run(on_update(update))

        handle.on("message", on_message)
        self._handles[key] = (handle, client)

    async def stop(self, key: MarketStreamKey) -> None:
        stream = self._handles.pop(key, None)
        if stream is not None:
            handle, client = stream
            await handle.unsubscribe()
            await client.websocket_streams.close_connection()


GLOBAL_MARKET_STREAM_HUB = MarketStreamHub(BinanceKlineWebSocketAdapter())


async def run_binance_kline_websocket_smoke(symbol: str = "BTCUSDT", interval: str = "1m", timeout_seconds: float = 10.0) -> dict:
    key = MarketStreamKey("BINANCE", symbol, interval)
    hub = MarketStreamHub(BinanceKlineWebSocketAdapter())
    subscription = await hub.subscribe(key)
    try:
        update = await asyncio.wait_for(subscription.get(), timeout=timeout_seconds)
        return {
            "received": True,
            "symbol": update.symbol,
            "interval": update.interval,
            "open_time": update.open_time,
            "event_time": update.event_time,
            "closed": update.is_closed,
        }
    finally:
        await subscription.unsubscribe()
