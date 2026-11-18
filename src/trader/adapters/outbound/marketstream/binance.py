"""Binance websocket kline connector and message normalization."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from trader.adapters.outbound.marketstream.hub import MarketStreamHub
from trader.core.marketdata.interfaces import DisconnectCallback, UpdateCallback
from trader.core.marketdata.stream import MarketStreamKey
from trader.core.marketdata.warmup import KlineUpdate, KlineUpdateError

BINANCE_SPOT_WS_STREAM_URL = "wss://stream.binance.com:443/stream"


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


def normalize_binance_kline_message(message: Any, exchange: str = "BINANCE") -> KlineUpdate:
    payload = _to_mapping(message)
    if "k" not in payload:
        raise KlineUpdateError("missing kline payload field 'k'")

    event_time_ms = _required(payload, "E", "event time")
    kline = _to_mapping(payload["k"])
    closed = _required(kline, "x", "closed flag")
    if not isinstance(closed, bool):
        raise KlineUpdateError("closed flag 'x' must be a boolean")

    return KlineUpdate(
        exchange=str(exchange),
        symbol=str(_required(kline, "s", "symbol") or _required(payload, "s", "symbol")),
        interval=str(_required(kline, "i", "interval")),
        open_time=_ms_to_seconds(_required(kline, "t", "open time")),
        close_time=_ms_to_seconds(_required(kline, "T", "close time")),
        open=float(_required(kline, "o", "open")),
        close=float(_required(kline, "c", "close")),
        high=float(_required(kline, "h", "high")),
        low=float(_required(kline, "l", "low")),
        volume=float(_required(kline, "v", "volume")),
        event_time=_ms_to_seconds(event_time_ms),
        is_closed=closed,
        vol_quote=float(kline.get("q", 0.0) or 0.0),
        trades=int(kline.get("n", 0) or 0),
        vol_taker_base=float(kline.get("V", 0.0) or 0.0),
        vol_taker_quote=float(kline.get("Q", 0.0) or 0.0),
        ignore=float(kline.get("B", 0.0) or 0.0),
    )


def _to_mapping(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True)
    if hasattr(value, "dict"):
        return value.dict()
    raise KlineUpdateError(f"unsupported Binance kline message type: {type(value).__name__}")


def _required(payload: dict, key: str, label: str) -> Any:
    if key not in payload or payload[key] is None:
        raise KlineUpdateError(f"missing {label} field '{key}'")
    return payload[key]


def _ms_to_seconds(value: Any) -> int:
    return int(int(value) / 1000)


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
