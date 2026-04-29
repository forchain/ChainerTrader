import os

import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.skipif(
    not os.environ.get("TRADER_BINANCE_WS_SMOKE"),
    reason="requires TRADER_BINANCE_WS_SMOKE=1 and outbound Binance WebSocket connectivity",
)
@pytest.mark.anyio
async def test_binance_kline_websocket_smoke_receives_one_message():
    from trader.live.stream import run_binance_kline_websocket_smoke

    result = await run_binance_kline_websocket_smoke(timeout_seconds=15.0)

    assert result["received"] is True
    assert result["symbol"] == "BTCUSDT"
    assert result["interval"] == "1m"
