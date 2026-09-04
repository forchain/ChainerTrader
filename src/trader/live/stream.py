from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Protocol

from trader.live.market_data import KlineUpdate, normalize_binance_kline_message
from trader.utils.kline import Kline
from trader.utils.symbol_interval import Interval, SymbolInterval, get_time_duration

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


@dataclass
class _PollingStreamState:
    key: MarketStreamKey
    on_update: UpdateCallback
    on_disconnect: DisconnectCallback | None
    next_poll_at: float
    baseline_initialized: bool = False
    last_published_open_time: int | None = None


class CcxtPollingMarketStreamAdapter:
    def __init__(
        self,
        *,
        exchange=None,
        poll_interval_seconds: float | None = None,
        min_request_spacing_seconds: float | None = None,
        closed_kline_delay_seconds: float = 5.0,
        startup_stagger_seconds: float = 10.0,
        fetch_limit: int = 2,
        now_func: Callable[[], float] | None = None,
        sleep_func: Callable[[float], Awaitable[None]] | None = None,
    ):
        self.exchange = exchange
        if min_request_spacing_seconds is None:
            min_request_spacing_seconds = 10.0 if poll_interval_seconds is None else float(poll_interval_seconds)
        self.min_request_spacing_seconds = max(0.0, float(min_request_spacing_seconds))
        self.poll_interval_seconds = self.min_request_spacing_seconds
        self.closed_kline_delay_seconds = max(0.0, float(closed_kline_delay_seconds))
        self.startup_stagger_seconds = max(0.0, float(startup_stagger_seconds))
        self.fetch_limit = max(2, int(fetch_limit))
        self.now_func = now_func or time.time
        self.sleep_func = sleep_func or asyncio.sleep
        self._streams: dict[MarketStreamKey, _PollingStreamState] = {}
        self._scheduler_task: asyncio.Task | None = None
        self._last_request_at: float | None = None
        self._wakeup = asyncio.Event()

    def set_exchange(self, exchange) -> None:
        self.exchange = exchange

    async def start(self, key: MarketStreamKey, on_update: UpdateCallback, on_disconnect: DisconnectCallback | None = None) -> None:
        if self.exchange is None:
            raise RuntimeError("CCXT polling market stream requires an exchange")
        if key in self._streams:
            return
        next_poll_at = self._now()
        self._streams[key] = _PollingStreamState(key=key, on_update=on_update, on_disconnect=on_disconnect, next_poll_at=next_poll_at)
        self._wakeup.set()
        logging.info(
            "CCXT polling scheduler stream registered: stream=%s min_request_spacing_seconds=%s closed_kline_delay_seconds=%s startup_stagger_seconds=%s next_poll_at=%s fetch_limit=%s",
            key.stream_name(),
            self.min_request_spacing_seconds,
            self.closed_kline_delay_seconds,
            self.startup_stagger_seconds,
            int(next_poll_at),
            self.fetch_limit,
        )
        if self._scheduler_task is None or self._scheduler_task.done():
            logging.info("CCXT polling scheduler started: min_request_spacing_seconds=%s", self.min_request_spacing_seconds)
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())

    async def stop(self, key: MarketStreamKey, reason: str = "") -> None:
        state = self._streams.pop(key, None)
        if state is None:
            return
        self._wakeup.set()
        logging.info("CCXT polling scheduler stream removed: stream=%s reason=%s", key.stream_name(), reason or "unspecified")
        if self._streams:
            return
        task = self._scheduler_task
        self._scheduler_task = None
        if task is None:
            return
        task.cancel()
        if task is asyncio.current_task():
            return
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _scheduler_loop(self) -> None:
        try:
            while True:
                if not self._streams:
                    return
                state = self._next_due_stream()
                now = self._now()
                if state is None:
                    await self.sleep_func(1.0)
                    continue
                sleep_seconds = state.next_poll_at - now
                if sleep_seconds > 0:
                    await self._sleep_or_wakeup(sleep_seconds)
                    continue
                if self._last_request_at is not None:
                    spacing_sleep = self.min_request_spacing_seconds - (now - self._last_request_at)
                    if spacing_sleep > 0:
                        await self._sleep_or_wakeup(spacing_sleep)
                        continue
                await self._poll_stream(state)
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("CCXT polling scheduler failed")

    def _next_due_stream(self) -> _PollingStreamState | None:
        if not self._streams:
            return None
        now = self._now()
        return min(
            self._streams.values(),
            key=lambda item: (
                0.0 if item.next_poll_at <= now else item.next_poll_at,
                self._interval_seconds(item.key),
                item.key.stream_name(),
            ),
        )

    async def _sleep_or_wakeup(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self._wakeup.clear()
        sleep_task = asyncio.create_task(self.sleep_func(seconds))
        wake_task = asyncio.create_task(self._wakeup.wait())
        done, pending = await asyncio.wait({sleep_task, wake_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        for task in done:
            await task

    @staticmethod
    def _interval_seconds(key: MarketStreamKey) -> int:
        return get_time_duration(Interval(key.interval))

    async def _poll_stream(self, state: _PollingStreamState) -> None:
        key = state.key
        now = self._now()
        self._last_request_at = now
        logging.info("CCXT polling fetch started: stream=%s reason=interval_due", key.stream_name())
        try:
            klines = self._closed_klines(key)
        except Exception:
            logging.exception("CCXT polling fetch failed: stream=%s", key.stream_name())
            state.next_poll_at = self._now() + max(self.min_request_spacing_seconds, 1.0)
            if state.on_disconnect is not None:
                await state.on_disconnect()
            return
        if not state.baseline_initialized:
            state.baseline_initialized = True
            state.last_published_open_time = int(klines[-1].open_time) if klines else None
            state.next_poll_at = self._next_poll_at(key, state.last_published_open_time)
            logging.info(
                "CCXT polling baseline initialized: stream=%s baseline_open_time=%s next_poll_at=%s",
                key.stream_name(),
                state.last_published_open_time,
                int(state.next_poll_at),
            )
            return
        pending = self._new_closed_klines(state, klines)
        for kline in pending:
            logging.debug(
                "CCXT polling market stream new closed kline: stream=%s open_time=%s close_time=%s close=%s volume=%s",
                key.stream_name(),
                int(kline.open_time),
                int(kline.close_time),
                kline.close,
                kline.volume,
            )
            await state.on_update(_kline_to_update(key, kline))
        state.next_poll_at = self._next_poll_at(key, state.last_published_open_time)
        logging.debug(
            "CCXT polling fetch completed: stream=%s new_closed_klines=%s next_poll_at=%s",
            key.stream_name(),
            len(pending),
            int(state.next_poll_at),
        )

    def _new_closed_klines(self, state: _PollingStreamState, klines: list[Kline]) -> list[Kline]:
        last_open_time = state.last_published_open_time
        pending = [kline for kline in klines if last_open_time is None or int(kline.open_time) > last_open_time]
        if pending:
            state.last_published_open_time = int(pending[-1].open_time)
        return pending

    def _next_poll_at(self, key: MarketStreamKey, latest_open_time: int | None) -> float:
        now = self._now()
        duration = get_time_duration(Interval(key.interval))
        if latest_open_time is None:
            current_open = int(now // duration) * duration
            target = current_open + duration + self.closed_kline_delay_seconds
        else:
            target = int(latest_open_time) + duration + self.closed_kline_delay_seconds
        if target <= now:
            periods = int((now - target) // duration) + 1
            target += periods * duration
        return float(target)

    def _now(self) -> float:
        return float(self.now_func())

    def _closed_klines(self, key: MarketStreamKey) -> list[Kline]:
        symbol_interval = _symbol_interval_from_key(key)
        klines = self.exchange.get_latest_klines(symbol_interval, self.fetch_limit) or []
        closed = [kline for kline in klines if _is_closed_kline(kline, now_wall_time=int(self._now()))]
        return sorted(closed, key=lambda item: int(item.open_time))


def _symbol_interval_from_key(key: MarketStreamKey) -> SymbolInterval:
    symbol = key.symbol
    if "-" not in symbol:
        for quote in ("USDT", "USDC", "BUSD", "BTC", "ETH"):
            if symbol.endswith(quote) and len(symbol) > len(quote):
                symbol = f"{symbol[:-len(quote)]}-{quote}"
                break
    return SymbolInterval(symbol, Interval(key.interval))


def _is_closed_kline(kline: Kline, now_wall_time: int | None = None) -> bool:
    import time

    now = int(time.time()) if now_wall_time is None else int(now_wall_time)
    return int(kline.close_time) <= now


def _kline_to_update(key: MarketStreamKey, kline: Kline) -> KlineUpdate:
    return KlineUpdate(
        exchange=key.exchange,
        symbol=key.symbol,
        interval=key.interval,
        open_time=int(kline.open_time),
        close_time=int(kline.close_time),
        open=float(kline.open),
        high=float(kline.high),
        low=float(kline.low),
        close=float(kline.close),
        volume=float(kline.volume),
        event_time=int(kline.close_time),
        is_closed=True,
        vol_quote=float(kline.vol_quote),
        trades=int(kline.trades),
        vol_taker_base=float(kline.vol_taker_base),
        vol_taker_quote=float(kline.vol_taker_quote),
        ignore=float(kline.ignore),
    )


GLOBAL_MARKET_STREAM_HUB = MarketStreamHub(CcxtPollingMarketStreamAdapter())


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
