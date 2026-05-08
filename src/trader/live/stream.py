from __future__ import annotations

import asyncio
import logging
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

    async def stop(self, key: MarketStreamKey, reason: str = "") -> None:
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
    def __init__(
        self,
        connector: MarketStreamConnector,
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


class BinanceKlineWebSocketAdapter:
    def __init__(self, *, stream_url: str | None = None):
        self.stream_url = stream_url
        self._client = None
        self._stream_client = None
        self._handles = {}
        self._disconnect_callbacks: dict[MarketStreamKey, DisconnectCallback] = {}
        self._stopping: set[MarketStreamKey] = set()
        self._connection_lock = asyncio.Lock()

    async def start(self, key: MarketStreamKey, on_update: UpdateCallback, on_disconnect: DisconnectCallback | None = None) -> None:
        from binance_common.configuration import ConfigurationWebSocketStreams
        from binance_sdk_spot import Spot

        async with self._connection_lock:
            if on_disconnect is not None:
                self._disconnect_callbacks[key] = on_disconnect
            if self._stream_client is None:
                config = ConfigurationWebSocketStreams(stream_url=self.stream_url or BINANCE_SPOT_WS_STREAM_URL)
                self._client = Spot(config_ws_streams=config)
                self._stream_client = self._client.websocket_streams
                self._attach_disconnect_callback(self._stream_client)
                await self._stream_client.create_connection()
            stream_client = self._stream_client
            try:
                handle = await stream_client.kline(symbol=key.symbol.lower(), interval=key.interval)
            except Exception:
                if on_disconnect is not None:
                    self._disconnect_callbacks.pop(key, None)
                raise

        def on_message(message) -> None:
            update = normalize_binance_kline_message(message, exchange=key.exchange)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(on_update(update))
            except RuntimeError:
                asyncio.run(on_update(update))

        handle.on("message", on_message)
        self._handles[key] = (handle, self._client)

    async def stop(self, key: MarketStreamKey, reason: str = "") -> None:
        async with self._connection_lock:
            stream = self._handles.pop(key, None)
            self._disconnect_callbacks.pop(key, None)
            client = stream[1] if stream is not None else None
            should_close = client is not None and all(existing_client is not client for _handle, existing_client in self._handles.values())
        if stream is not None:
            handle, client = stream
            stop_reason = reason or "unspecified"
            logging.info("Stopping Binance kline websocket for %s: reason=%s", key.stream_name(), stop_reason)
            self._stopping.add(key)
            try:
                try:
                    await handle.unsubscribe()
                    logging.info("Unsubscribed Binance kline stream for %s: reason=%s", key.stream_name(), stop_reason)
                except Exception as exc:
                    logging.warning("Binance kline unsubscribe failed for %s: reason=%s error=%s", key.stream_name(), stop_reason, exc)
                finally:
                    self._forget_sdk_stream_mapping(key.stream_name())
                if should_close:
                    try:
                        logging.info("Closing Binance kline websocket for %s: reason=%s", key.stream_name(), stop_reason)
                        await client.websocket_streams.close_connection()
                        logging.info("Closed Binance kline websocket for %s: reason=%s", key.stream_name(), stop_reason)
                    except Exception as exc:
                        logging.warning("Binance kline websocket close failed for %s: reason=%s error=%s", key.stream_name(), stop_reason, exc)
                    finally:
                        async with self._connection_lock:
                            if self._client is client and not self._handles:
                                self._client = None
                                self._stream_client = None
            finally:
                self._stopping.discard(key)

    def _attach_disconnect_callback(self, stream_client) -> None:
        original_receive_loop = stream_client.receive_loop

        async def receive_loop_with_disconnect(connection) -> None:
            connection_id = getattr(connection, "id", None) or getattr(connection, "connection_id", None) or "unknown"
            try:
                await original_receive_loop(connection)
            except asyncio.CancelledError:
                logging.info(
                    "Binance kline websocket receive loop cancelled: connection_id=%s reconnect=%s stopping=%s",
                    connection_id,
                    getattr(connection, "reconnect", False),
                    bool(self._stopping),
                )
                raise
            except Exception as exc:
                logging.warning(
                    "Binance kline websocket receive loop failed: connection_id=%s reconnect=%s stopping=%s error=%s",
                    connection_id,
                    getattr(connection, "reconnect", False),
                    bool(self._stopping),
                    exc,
                )
            else:
                logging.warning(
                    "Binance kline websocket receive loop ended: connection_id=%s reconnect=%s stopping=%s",
                    connection_id,
                    getattr(connection, "reconnect", False),
                    bool(self._stopping),
                )
            finally:
                if self._stopping or getattr(connection, "reconnect", False):
                    logging.info(
                        "Binance kline websocket receive loop ended without hub reconnect: connection_id=%s reconnect=%s stopping=%s",
                        connection_id,
                        getattr(connection, "reconnect", False),
                        bool(self._stopping),
                    )
                    return
                callbacks = list(self._disconnect_callbacks.items())
                streams = ", ".join(key.stream_name() for key, _callback in callbacks)
                logging.warning(
                    "Binance kline websocket disconnected: connection_id=%s streams=%s; scheduling reconnect",
                    connection_id,
                    streams,
                )
                async with self._connection_lock:
                    self._client = None
                    self._stream_client = None
                for _key, on_disconnect in callbacks:
                    asyncio.create_task(on_disconnect())

        stream_client.receive_loop = receive_loop_with_disconnect

    @staticmethod
    def _forget_sdk_stream_mapping(stream_name: str) -> None:
        try:
            from binance_common.websocket import global_stream_connections
        except Exception:
            return

        connection = global_stream_connections.stream_connections_map.pop(stream_name, None)
        for attr in ("stream_callback_map", "response_types"):
            mapping = getattr(connection, attr, None)
            if mapping is not None:
                mapping.pop(stream_name, None)


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
