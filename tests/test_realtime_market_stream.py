import asyncio
import logging
from contextlib import suppress
from types import SimpleNamespace

import pytest

from trader.live.market_data import normalize_binance_kline_message
from trader.live.stream import (
    GLOBAL_MARKET_STREAM_HUB,
    BinanceKlineWebSocketAdapter,
    CcxtPollingMarketStreamAdapter,
    MarketStreamHub,
    MarketStreamKey,
    MarketStreamState,
)
from trader.utils.kline import Kline

BASE = 1_714_281_600


@pytest.fixture
def anyio_backend():
    return "asyncio"


class RecordingConnector:
    def __init__(self):
        self.started = []
        self.stopped = []
        self.stop_reasons = []
        self.callbacks = {}

    async def start(self, key, on_update, on_disconnect=None):
        self.started.append(key)
        self.callbacks[key] = on_update

    async def stop(self, key, reason=""):
        self.stopped.append(key)
        self.stop_reasons.append(reason)


def _update(symbol="BTCUSDT", interval="1m", open_time=BASE, closed=False):
    return normalize_binance_kline_message(
        {
            "e": "kline",
            "E": (open_time + 10) * 1000,
            "s": symbol,
            "k": {
                "t": open_time * 1000,
                "T": (open_time + 59) * 1000 + 999,
                "s": symbol,
                "i": interval,
                "o": "100",
                "c": "101",
                "h": "102",
                "l": "99",
                "v": "1",
                "n": 1,
                "x": closed,
            },
        }
    )


def _kline(open_time=BASE):
    return Kline(open_time, 100.0, 102.0, 99.0, 101.0, open_time + 59, 1.0, 0.0, 1, 0.0, 0.0)


class FakeClock:
    def __init__(self, now: float, *, auto_advance: bool = True):
        self.now = float(now)
        self.auto_advance = bool(auto_advance)
        self.sleeps = []

    def time(self):
        return self.now

    async def sleep(self, seconds):
        seconds = max(0.0, float(seconds))
        self.sleeps.append(seconds)
        if self.auto_advance:
            self.now += seconds
        await asyncio.sleep(0)


def test_global_market_stream_hub_defaults_to_ccxt_polling_not_binance_websocket():
    assert isinstance(GLOBAL_MARKET_STREAM_HUB.connector, CcxtPollingMarketStreamAdapter)
    assert not isinstance(GLOBAL_MARKET_STREAM_HUB.connector, BinanceKlineWebSocketAdapter)
    assert GLOBAL_MARKET_STREAM_HUB.connector.poll_interval_seconds == 10.0


@pytest.mark.anyio
async def test_ccxt_polling_adapter_publishes_new_closed_candle_and_stops():
    class FakeExchange:
        def __init__(self):
            self.calls = 0

        def get_latest_klines(self, symbol_interval, limit):
            self.calls += 1
            if self.calls == 1:
                return [_kline(BASE - 60)]
            return [_kline(BASE - 60), _kline(BASE)]

    updates = []
    clock = FakeClock(BASE + 30)
    adapter = CcxtPollingMarketStreamAdapter(
        exchange=FakeExchange(),
        poll_interval_seconds=0.0,
        closed_kline_delay_seconds=5.0,
        startup_stagger_seconds=0.0,
        now_func=clock.time,
        sleep_func=clock.sleep,
    )
    key = MarketStreamKey("BINANCE", "BTCUSDT", "1m")

    async def on_update(update):
        updates.append(update)
        await adapter.stop(key, reason="test complete")

    await adapter.start(key, on_update)
    for _ in range(10):
        if updates:
            break
        await asyncio.sleep(0)

    assert [update.open_time for update in updates] == [BASE]
    assert updates[0].is_closed is True


@pytest.mark.anyio
async def test_ccxt_polling_adapter_logs_baseline_and_new_closed_candles(caplog):
    class FakeExchange:
        def __init__(self):
            self.calls = 0

        def get_latest_klines(self, symbol_interval, limit):
            self.calls += 1
            if self.calls == 1:
                return [_kline(BASE - 60)]
            return [_kline(BASE - 60), _kline(BASE)]

    updates = []
    clock = FakeClock(BASE + 30)
    adapter = CcxtPollingMarketStreamAdapter(
        exchange=FakeExchange(),
        poll_interval_seconds=0.0,
        closed_kline_delay_seconds=5.0,
        startup_stagger_seconds=0.0,
        now_func=clock.time,
        sleep_func=clock.sleep,
    )
    key = MarketStreamKey("BINANCE", "BTCUSDT", "1m")

    async def on_update(update):
        updates.append(update)
        await adapter.stop(key, reason="test complete")

    with caplog.at_level(logging.DEBUG):
        await adapter.start(key, on_update)
        for _ in range(10):
            if updates:
                break
            await asyncio.sleep(0)

    assert "CCXT polling scheduler stream registered" in caplog.text
    assert "baseline_open_time" in caplog.text
    assert "CCXT polling market stream new closed kline" in caplog.text
    assert any(
        record.levelno == logging.DEBUG and "CCXT polling market stream new closed kline" in record.message
        for record in caplog.records
    )


@pytest.mark.anyio
async def test_ccxt_polling_scheduler_does_not_overpoll_daily_stream_before_next_close():
    class FakeExchange:
        def __init__(self):
            self.calls = 0

        def get_latest_klines(self, symbol_interval, limit):
            self.calls += 1
            return [_kline(BASE)]

    clock = FakeClock(BASE + 86_400 + 30, auto_advance=False)
    exchange = FakeExchange()
    adapter = CcxtPollingMarketStreamAdapter(
        exchange=exchange,
        min_request_spacing_seconds=0.0,
        closed_kline_delay_seconds=5.0,
        startup_stagger_seconds=0.0,
        now_func=clock.time,
        sleep_func=clock.sleep,
    )
    key = MarketStreamKey("BINANCE", "BTCUSDT", "1d")

    async def on_update(update):
        raise AssertionError("daily baseline must not publish existing closed kline")

    await adapter.start(key, on_update)
    for _ in range(5):
        await asyncio.sleep(0)

    assert exchange.calls == 1
    assert clock.sleeps
    assert min(clock.sleeps) > 3600
    await adapter.stop(key, reason="test cleanup")


@pytest.mark.anyio
async def test_ccxt_polling_scheduler_waits_for_minute_close_before_refetching():
    class FakeExchange:
        def __init__(self):
            self.calls = 0

        def get_latest_klines(self, symbol_interval, limit):
            self.calls += 1
            if self.calls == 1:
                return [_kline(BASE - 60)]
            return [_kline(BASE - 60), _kline(BASE)]

    clock = FakeClock(BASE + 30)
    exchange = FakeExchange()
    updates = []
    adapter = CcxtPollingMarketStreamAdapter(
        exchange=exchange,
        min_request_spacing_seconds=0.0,
        closed_kline_delay_seconds=5.0,
        startup_stagger_seconds=0.0,
        now_func=clock.time,
        sleep_func=clock.sleep,
    )
    key = MarketStreamKey("BINANCE", "BTCUSDT", "1m")

    async def on_update(update):
        updates.append(update)
        await adapter.stop(key, reason="test complete")

    await adapter.start(key, on_update)
    for _ in range(10):
        if updates:
            break
        await asyncio.sleep(0)

    assert exchange.calls == 2
    assert [update.open_time for update in updates] == [BASE]
    assert 35.0 in clock.sleeps


@pytest.mark.anyio
async def test_ccxt_polling_scheduler_applies_global_spacing_across_due_streams():
    class FakeExchange:
        def __init__(self):
            self.calls = []

        def get_latest_klines(self, symbol_interval, limit):
            self.calls.append((symbol_interval.name(), clock.time()))
            return [_kline(BASE)]

    clock = FakeClock(BASE + 30)
    exchange = FakeExchange()
    adapter = CcxtPollingMarketStreamAdapter(
        exchange=exchange,
        min_request_spacing_seconds=10.0,
        closed_kline_delay_seconds=5.0,
        startup_stagger_seconds=0.0,
        now_func=clock.time,
        sleep_func=clock.sleep,
    )

    await adapter.start(MarketStreamKey("BINANCE", "BTCUSDT", "1m"), lambda update: None)
    await adapter.start(MarketStreamKey("BINANCE", "ETHUSDT", "1m"), lambda update: None)
    for _ in range(10):
        if len(exchange.calls) >= 2:
            break
        await asyncio.sleep(0)

    assert len(exchange.calls) >= 2
    assert exchange.calls[1][1] - exchange.calls[0][1] >= 10.0
    await adapter.stop(MarketStreamKey("BINANCE", "BTCUSDT", "1m"), reason="test cleanup")
    await adapter.stop(MarketStreamKey("BINANCE", "ETHUSDT", "1m"), reason="test cleanup")


@pytest.mark.anyio
async def test_ccxt_polling_scheduler_prioritizes_minute_stream_after_daily_baseline():
    class FakeExchange:
        def __init__(self):
            self.calls = []
            self.third_call = asyncio.Event()

        def get_latest_klines(self, symbol_interval, limit):
            self.calls.append(symbol_interval.name())
            if len(self.calls) >= 3:
                self.third_call.set()
            return [_kline(BASE)]

    clock = FakeClock(BASE + 30)
    exchange = FakeExchange()
    adapter = CcxtPollingMarketStreamAdapter(
        exchange=exchange,
        min_request_spacing_seconds=10.0,
        closed_kline_delay_seconds=5.0,
        startup_stagger_seconds=10.0,
        now_func=clock.time,
        sleep_func=clock.sleep,
    )

    async def on_update(update):
        return None

    await adapter.start(MarketStreamKey("BINANCE", "BTCUSDT", "1d"), on_update)
    clock.now += 1
    await adapter.start(MarketStreamKey("BINANCE", "ETHUSDT", "1d"), on_update)
    clock.now += 1
    await adapter.start(MarketStreamKey("BINANCE", "BTCUSDT", "1m"), on_update)
    await asyncio.wait_for(exchange.third_call.wait(), timeout=1.0)

    assert exchange.calls[0] == "BTCUSDT-1m"
    assert exchange.calls.index("BTCUSDT-1m") < exchange.calls.index("ETHUSDT-1d")
    await adapter.stop(MarketStreamKey("BINANCE", "BTCUSDT", "1d"), reason="test cleanup")
    await adapter.stop(MarketStreamKey("BINANCE", "ETHUSDT", "1d"), reason="test cleanup")
    await adapter.stop(MarketStreamKey("BINANCE", "BTCUSDT", "1m"), reason="test cleanup")


@pytest.mark.anyio
async def test_ccxt_polling_scheduler_wakes_when_shorter_stream_registers_during_long_sleep():
    class BlockingSleep:
        def __init__(self, clock):
            self.clock = clock
            self.long_sleep_started = asyncio.Event()
            self.long_sleep_cancelled = False

        async def sleep(self, seconds):
            seconds = float(seconds)
            if seconds > 3600:
                self.long_sleep_started.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    self.long_sleep_cancelled = True
                    raise
            self.clock.now += max(0.0, seconds)
            await asyncio.sleep(0)

    class FakeExchange:
        def __init__(self):
            self.calls = []
            self.minute_called = asyncio.Event()

        def get_latest_klines(self, symbol_interval, limit):
            self.calls.append(symbol_interval.name())
            if symbol_interval.name().endswith("-1m"):
                self.minute_called.set()
                return [_kline(BASE - 60)]
            return []

    clock = FakeClock(BASE + 30, auto_advance=False)
    sleep = BlockingSleep(clock)
    exchange = FakeExchange()
    adapter = CcxtPollingMarketStreamAdapter(
        exchange=exchange,
        min_request_spacing_seconds=10.0,
        closed_kline_delay_seconds=5.0,
        startup_stagger_seconds=10.0,
        now_func=clock.time,
        sleep_func=sleep.sleep,
    )

    async def on_update(update):
        return None

    await adapter.start(MarketStreamKey("BINANCE", "BTCUSDT", "1d"), on_update)
    await asyncio.wait_for(sleep.long_sleep_started.wait(), timeout=1.0)
    await adapter.start(MarketStreamKey("BINANCE", "BTCUSDT", "1m"), on_update)
    await asyncio.wait_for(exchange.minute_called.wait(), timeout=1.0)

    assert exchange.calls[:2] == ["BTCUSDT-1d", "BTCUSDT-1m"]
    assert sleep.long_sleep_cancelled is True
    await adapter.stop(MarketStreamKey("BINANCE", "BTCUSDT", "1d"), reason="test cleanup")
    await adapter.stop(MarketStreamKey("BINANCE", "BTCUSDT", "1m"), reason="test cleanup")


@pytest.mark.anyio
async def test_aiohttp_default_autoping_replies_to_server_ping_payload():
    from aiohttp import ClientSession, WSMsgType, web

    received_pong_payloads = []
    received_pong = asyncio.Event()

    async def ws_handler(request):
        ws = web.WebSocketResponse(autoping=False)
        await ws.prepare(request)
        await ws.ping(b"binance-heartbeat")
        try:
            msg = await ws.receive(timeout=1.0)
            if msg.type == WSMsgType.PONG:
                received_pong_payloads.append(msg.data)
                received_pong.set()
        finally:
            await ws.close()
        return ws

    app = web.Application()
    app.router.add_get("/stream", ws_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    assert site._server is not None
    port = site._server.sockets[0].getsockname()[1]

    try:
        async with ClientSession() as session:
            async with session.ws_connect(f"http://127.0.0.1:{port}/stream") as ws:
                client_reader = asyncio.create_task(ws.receive())
                try:
                    await asyncio.wait_for(received_pong.wait(), timeout=1.0)
                finally:
                    client_reader.cancel()
                    with suppress(asyncio.CancelledError):
                        await client_reader
    finally:
        await runner.cleanup()

    assert received_pong_payloads == [b"binance-heartbeat"]


@pytest.mark.anyio
async def test_market_stream_hub_reuses_same_market_subscription_and_fans_out_updates():
    connector = RecordingConnector()
    hub = MarketStreamHub(connector)
    key = MarketStreamKey("BINANCE", "BTCUSDT", "1m")

    first = await hub.subscribe(key)
    second = await hub.subscribe(key)
    await hub.publish(key, _update())

    assert connector.started == [key]
    assert await first.get() == await second.get()
    assert hub.status(key).subscriber_count == 2


@pytest.mark.anyio
async def test_market_stream_hub_uses_independent_streams_for_different_markets():
    connector = RecordingConnector()
    hub = MarketStreamHub(connector)
    btc = MarketStreamKey("BINANCE", "BTCUSDT", "1m")
    eth = MarketStreamKey("BINANCE", "ETHUSDT", "1d")

    await hub.subscribe(btc)
    await hub.subscribe(eth)

    assert connector.started == [btc, eth]
    assert hub.status(btc).subscriber_count == 1
    assert hub.status(eth).subscriber_count == 1


@pytest.mark.anyio
async def test_market_stream_hub_cleans_up_connector_when_last_subscriber_unsubscribes():
    connector = RecordingConnector()
    hub = MarketStreamHub(connector)
    key = MarketStreamKey("BINANCE", "BTCUSDT", "1m")

    first = await hub.subscribe(key)
    second = await hub.subscribe(key)
    await first.unsubscribe()

    assert connector.stopped == []
    await second.unsubscribe()

    assert connector.stopped == [key]
    assert connector.stop_reasons == ["last subscriber unsubscribed"]
    assert hub.status(key).state == MarketStreamState.STOPPED
    assert hub.status(key).subscriber_count == 0


@pytest.mark.anyio
async def test_market_stream_hub_runs_reconnect_catchup_before_returning_to_running():
    connector = RecordingConnector()
    caught_up = []

    async def catch_up(key):
        caught_up.append(key)

    hub = MarketStreamHub(connector, catch_up=catch_up)
    key = MarketStreamKey("BINANCE", "BTCUSDT", "1m")
    await hub.subscribe(key)

    await hub.handle_disconnect(key)

    assert caught_up == [key]
    assert hub.status(key).state == MarketStreamState.RUNNING


@pytest.mark.anyio
async def test_market_stream_hub_restarts_connector_on_disconnect():
    connector = RecordingConnector()
    hub = MarketStreamHub(connector)
    key = MarketStreamKey("BINANCE", "BTCUSDT", "1m")
    await hub.subscribe(key)

    await hub.handle_disconnect(key)

    assert connector.stopped == [key]
    assert connector.stop_reasons == ["websocket disconnected"]
    assert connector.started == [key, key]
    assert hub.status(key).state == MarketStreamState.RUNNING


@pytest.mark.anyio
async def test_market_stream_hub_restarts_when_connector_stop_fails_on_disconnect():
    class StopFailingConnector(RecordingConnector):
        async def stop(self, key, reason=""):
            self.stopped.append(key)
            self.stop_reasons.append(reason)
            raise RuntimeError("Cannot write to closing transport")

    connector = StopFailingConnector()
    caught_up = []

    async def catch_up(key):
        caught_up.append(key)

    hub = MarketStreamHub(connector, catch_up=catch_up)
    key = MarketStreamKey("BINANCE", "BTCUSDT", "1m")
    await hub.subscribe(key)

    await hub.handle_disconnect(key)

    assert connector.stopped == [key]
    assert connector.stop_reasons == ["websocket disconnected"]
    assert connector.started == [key, key]
    assert caught_up == [key]
    status = hub.status(key)
    assert status.state == MarketStreamState.RUNNING
    assert status.last_error is None


@pytest.mark.anyio
async def test_market_stream_hub_retries_until_restart_succeeds_after_disconnect():
    class RestartFailingConnector(RecordingConnector):
        async def start(self, key, on_update, on_disconnect=None):
            self.started.append(key)
            self.callbacks[key] = on_update
            if len(self.started) == 2:
                raise ValueError("No WebSocket connections available.")

    connector = RestartFailingConnector()
    hub = MarketStreamHub(connector, reconnect_delays=(0.0,))
    key = MarketStreamKey("BINANCE", "BTCUSDT", "1m")
    await hub.subscribe(key)

    await hub.handle_disconnect(key)
    for _ in range(10):
        if len(connector.started) >= 3:
            break
        await asyncio.sleep(0)

    status = hub.status(key)
    assert connector.stopped == [key]
    assert connector.stop_reasons == ["websocket disconnected"]
    assert connector.started == [key, key, key]
    assert status.state == MarketStreamState.RUNNING
    assert status.subscriber_count == 1
    assert status.last_error is None


@pytest.mark.anyio
async def test_binance_kline_adapter_opens_connection_before_subscribing(monkeypatch):
    import binance_sdk_spot

    calls = []

    class FakeHandle:
        def on(self, event, callback):
            calls.append(("on", event))

        async def unsubscribe(self):
            calls.append(("unsubscribe",))

    class FakeWebSocketStreams:
        async def receive_loop(self, connection):
            return None

        async def create_connection(self):
            calls.append(("create_connection",))

        async def kline(self, symbol, interval):
            calls.append(("kline", symbol, interval))
            return FakeHandle()

        async def close_connection(self):
            calls.append(("close_connection",))

    class FakeSpot:
        def __init__(self, config_ws_streams):
            self.config_ws_streams = config_ws_streams
            self.websocket_streams = FakeWebSocketStreams()

    monkeypatch.setattr(binance_sdk_spot, "Spot", FakeSpot)
    adapter = BinanceKlineWebSocketAdapter()
    key = MarketStreamKey("BINANCE", "BTCUSDT", "1m")

    async def on_update(update):
        return None

    await adapter.start(key, on_update)
    await adapter.stop(key)

    assert adapter._handles == {}
    assert calls == [
        ("create_connection",),
        ("kline", "btcusdt", "1m"),
        ("on", "message"),
        ("unsubscribe",),
        ("close_connection",),
    ]


@pytest.mark.anyio
async def test_binance_kline_adapter_reuses_one_connection_for_multiple_kline_streams(monkeypatch):
    import binance_sdk_spot

    calls = []

    class FakeHandle:
        def __init__(self, stream):
            self.stream = stream

        def on(self, event, callback):
            calls.append(("on", self.stream, event))

        async def unsubscribe(self):
            calls.append(("unsubscribe", self.stream))

    class FakeWebSocketStreams:
        def __init__(self):
            self.connections = []

        async def receive_loop(self, connection):
            return None

        async def create_connection(self):
            calls.append(("create_connection",))
            self.connections.append(SimpleNamespace(reconnect=False))

        async def kline(self, symbol, interval):
            stream = f"{symbol}@kline_{interval}"
            calls.append(("kline", symbol, interval))
            return FakeHandle(stream)

        async def close_connection(self):
            calls.append(("close_connection",))
            self.connections.clear()

    class FakeSpot:
        def __init__(self, config_ws_streams):
            self.config_ws_streams = config_ws_streams
            self.websocket_streams = FakeWebSocketStreams()

    monkeypatch.setattr(binance_sdk_spot, "Spot", FakeSpot)
    adapter = BinanceKlineWebSocketAdapter()
    btc = MarketStreamKey("BINANCE", "BTCUSDT", "1m")
    eth = MarketStreamKey("BINANCE", "ETHUSDT", "1m")

    async def on_update(update):
        return None

    await adapter.start(btc, on_update)
    await adapter.start(eth, on_update)
    await adapter.stop(btc, reason="test cleanup")
    await adapter.stop(eth, reason="test cleanup")

    assert calls == [
        ("create_connection",),
        ("kline", "btcusdt", "1m"),
        ("on", "btcusdt@kline_1m", "message"),
        ("kline", "ethusdt", "1m"),
        ("on", "ethusdt@kline_1m", "message"),
        ("unsubscribe", "btcusdt@kline_1m"),
        ("unsubscribe", "ethusdt@kline_1m"),
        ("close_connection",),
    ]


@pytest.mark.anyio
async def test_binance_kline_adapter_closes_connection_when_unsubscribe_transport_is_closing(monkeypatch, caplog):
    import binance_sdk_spot

    calls = []

    class FakeHandle:
        def on(self, event, callback):
            calls.append(("on", event))

        async def unsubscribe(self):
            calls.append(("unsubscribe",))
            raise RuntimeError("Cannot write to closing transport")

    class FakeWebSocketStreams:
        async def receive_loop(self, connection):
            return None

        async def create_connection(self):
            calls.append(("create_connection",))

        async def kline(self, symbol, interval):
            calls.append(("kline", symbol, interval))
            return FakeHandle()

        async def close_connection(self):
            calls.append(("close_connection",))

    class FakeSpot:
        def __init__(self, config_ws_streams):
            self.config_ws_streams = config_ws_streams
            self.websocket_streams = FakeWebSocketStreams()

    monkeypatch.setattr(binance_sdk_spot, "Spot", FakeSpot)
    adapter = BinanceKlineWebSocketAdapter()
    key = MarketStreamKey("BINANCE", "BTCUSDT", "1m")

    async def on_update(update):
        return None

    await adapter.start(key, on_update)
    with caplog.at_level(logging.INFO):
        await adapter.stop(key, reason="websocket disconnected")

    assert adapter._handles == {}
    assert calls == [
        ("create_connection",),
        ("kline", "btcusdt", "1m"),
        ("on", "message"),
        ("unsubscribe",),
        ("close_connection",),
    ]
    assert "reason=websocket disconnected" in caplog.text
    assert "Cannot write to closing transport" in caplog.text


@pytest.mark.anyio
async def test_binance_kline_adapter_removes_sdk_stream_mapping_when_unsubscribe_transport_is_closing(monkeypatch):
    import binance_sdk_spot
    from binance_common.websocket import global_stream_connections

    calls = []

    class FakeHandle:
        def on(self, event, callback):
            calls.append(("on", event))

        async def unsubscribe(self):
            calls.append(("unsubscribe",))
            raise RuntimeError("Cannot write to closing transport")

    class FakeWebSocketStreams:
        async def receive_loop(self, connection):
            return None

        async def create_connection(self):
            calls.append(("create_connection",))

        async def kline(self, symbol, interval):
            calls.append(("kline", symbol, interval))
            return FakeHandle()

        async def close_connection(self):
            calls.append(("close_connection",))

    class FakeSpot:
        def __init__(self, config_ws_streams):
            self.config_ws_streams = config_ws_streams
            self.websocket_streams = FakeWebSocketStreams()

    monkeypatch.setattr(binance_sdk_spot, "Spot", FakeSpot)
    adapter = BinanceKlineWebSocketAdapter()
    key = MarketStreamKey("BINANCE", "BTCUSDT", "1m")
    stream_name = key.stream_name()

    async def on_update(update):
        return None

    await adapter.start(key, on_update)
    global_stream_connections.stream_connections_map[stream_name] = object()
    try:
        await adapter.stop(key)

        assert stream_name not in global_stream_connections.stream_connections_map
    finally:
        global_stream_connections.stream_connections_map.pop(stream_name, None)


@pytest.mark.anyio
async def test_binance_kline_adapter_invokes_disconnect_callback_when_sdk_receive_loop_returns(monkeypatch, caplog):
    import binance_sdk_spot

    calls = []
    disconnected = asyncio.Event()

    class FakeHandle:
        def on(self, event, callback):
            calls.append(("on", event))

        async def unsubscribe(self):
            calls.append(("unsubscribe",))

    class FakeWebSocketStreams:
        async def create_connection(self):
            calls.append(("create_connection",))
            self.receive_task = asyncio.create_task(self.receive_loop(SimpleNamespace(reconnect=False)))
            await asyncio.sleep(0)

        async def receive_loop(self, connection):
            calls.append(("receive_loop", connection.reconnect))

        async def kline(self, symbol, interval):
            calls.append(("kline", symbol, interval))
            return FakeHandle()

        async def close_connection(self):
            calls.append(("close_connection",))

    class FakeSpot:
        def __init__(self, config_ws_streams):
            self.config_ws_streams = config_ws_streams
            self.websocket_streams = FakeWebSocketStreams()

    monkeypatch.setattr(binance_sdk_spot, "Spot", FakeSpot)
    adapter = BinanceKlineWebSocketAdapter()
    key = MarketStreamKey("BINANCE", "BTCUSDT", "1m")

    async def on_update(update):
        return None

    async def on_disconnect():
        disconnected.set()

    with caplog.at_level(logging.INFO):
        await adapter.start(key, on_update, on_disconnect)
        await asyncio.wait_for(disconnected.wait(), timeout=0.1)
        await adapter.stop(key, reason="test cleanup")

    assert ("receive_loop", False) in calls
    assert "Binance kline websocket receive loop ended" in caplog.text
    assert "streams=btcusdt@kline_1m" in caplog.text
    assert "scheduling reconnect" in caplog.text


@pytest.mark.anyio
async def test_binance_kline_adapter_notifies_all_streams_when_shared_connection_ends(monkeypatch):
    import binance_sdk_spot

    calls = []
    disconnected = []
    stream_clients = []
    disconnect_now = asyncio.Event()

    class FakeHandle:
        def __init__(self, stream):
            self.stream = stream

        def on(self, event, callback):
            calls.append(("on", self.stream, event))

        async def unsubscribe(self):
            calls.append(("unsubscribe", self.stream))

    class FakeWebSocketStreams:
        def __init__(self):
            self.connections = []
            stream_clients.append(self)

        async def create_connection(self):
            calls.append(("create_connection", len(stream_clients)))
            self.connections.append(SimpleNamespace(reconnect=False))
            self.receive_task = asyncio.create_task(self.receive_loop(self.connections[-1]))
            await asyncio.sleep(0)

        async def receive_loop(self, connection):
            await disconnect_now.wait()
            calls.append(("receive_loop", len(stream_clients), connection.reconnect))

        async def kline(self, symbol, interval):
            stream = f"{symbol}@kline_{interval}"
            calls.append(("kline", stream, len(stream_clients)))
            return FakeHandle(stream)

        async def close_connection(self):
            calls.append(("close_connection", len(stream_clients)))
            self.connections.clear()

    class FakeSpot:
        def __init__(self, config_ws_streams):
            self.config_ws_streams = config_ws_streams
            self.websocket_streams = FakeWebSocketStreams()

    monkeypatch.setattr(binance_sdk_spot, "Spot", FakeSpot)
    adapter = BinanceKlineWebSocketAdapter()
    btc = MarketStreamKey("BINANCE", "BTCUSDT", "1m")
    eth = MarketStreamKey("BINANCE", "ETHUSDT", "1m")

    async def on_update(update):
        return None

    async def btc_disconnect():
        disconnected.append(btc)

    async def eth_disconnect():
        disconnected.append(eth)

    await adapter.start(btc, on_update, btc_disconnect)
    await adapter.start(eth, on_update, eth_disconnect)
    disconnect_now.set()

    for _ in range(10):
        if set(disconnected) == {btc, eth}:
            break
        await asyncio.sleep(0)

    assert set(disconnected) == {btc, eth}

    await adapter.start(btc, on_update, btc_disconnect)

    assert len(stream_clients) == 2
    assert ("create_connection", 2) in calls
