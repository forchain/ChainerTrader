import pytest

from trader.live.market_data import normalize_binance_kline_message
from trader.live.stream import BinanceKlineWebSocketAdapter, MarketStreamHub, MarketStreamKey, MarketStreamState

BASE = 1_714_281_600


@pytest.fixture
def anyio_backend():
    return "asyncio"


class RecordingConnector:
    def __init__(self):
        self.started = []
        self.stopped = []
        self.callbacks = {}

    async def start(self, key, on_update, on_disconnect=None):
        self.started.append(key)
        self.callbacks[key] = on_update

    async def stop(self, key):
        self.stopped.append(key)


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
    assert connector.started == [key, key]
    assert hub.status(key).state == MarketStreamState.RUNNING


@pytest.mark.anyio
async def test_market_stream_hub_restarts_when_connector_stop_fails_on_disconnect():
    class StopFailingConnector(RecordingConnector):
        async def stop(self, key):
            self.stopped.append(key)
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
    assert connector.started == [key, key]
    assert caught_up == [key]
    status = hub.status(key)
    assert status.state == MarketStreamState.RUNNING
    assert status.last_error == "Cannot write to closing transport"


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
async def test_binance_kline_adapter_closes_connection_when_unsubscribe_transport_is_closing(monkeypatch):
    import binance_sdk_spot

    calls = []

    class FakeHandle:
        def on(self, event, callback):
            calls.append(("on", event))

        async def unsubscribe(self):
            calls.append(("unsubscribe",))
            raise RuntimeError("Cannot write to closing transport")

    class FakeWebSocketStreams:
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
