import os
from dataclasses import dataclass

import pytest
from binance_common.configuration import ConfigurationRestAPI
from binance_common.constants import SPOT_REST_API_PROD_URL
from binance_sdk_spot import Spot
from dotenv import load_dotenv

from trader.common.config import Config, new_and_env
from trader.exchange.binance.exchange import BinanceExchange
from trader.exchange.exchange_config import parse_exchange_config
from trader.live.runtime import RealtimeLiveStrategyRuntime
from trader.live.stream import run_binance_kline_websocket_smoke
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import Interval, SymbolInterval

pytestmark = pytest.mark.skipif(
    not os.environ.get("TRADER_BINANCE_INTEGRATION"),
    reason="requires TRADER_BINANCE_INTEGRATION=1 and outbound Binance connectivity",
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
def binance_exchange():
    load_dotenv()
    cfg = new_and_env()
    ex_cfg = parse_exchange_config(cfg.exchange)
    return BinanceExchange(ex_cfg)


def _symbol_interval():
    return SymbolInterval("BTC-USDT", Interval.INTERVAL_1m)


def test_binance_public_rest_supports_time_exchange_info_and_latest_klines(binance_exchange):
    assert binance_exchange.ping() is True
    assert binance_exchange.time() is not None

    exchange_info = binance_exchange.exchange_info("BTCUSDT")
    assert exchange_info is not None
    assert exchange_info.symbols
    assert exchange_info.symbols[0].symbol == "BTCUSDT"

    klines = binance_exchange.get_latest_klines(_symbol_interval(), 5)
    assert klines is not None
    assert len(klines) == 5
    assert all(k.open_time < k.close_time for k in klines)
    assert klines == sorted(klines, key=lambda item: item.open_time)


def test_binance_public_rest_supports_bounded_backfill_by_end_time(binance_exchange):
    latest = binance_exchange.get_latest_klines(_symbol_interval(), 2)
    assert latest is not None
    assert len(latest) == 2

    bounded = binance_exchange.get_klines_by_end(_symbol_interval(), latest[-1].close_time, limit=2)
    assert bounded is not None
    assert len(bounded) == 2
    assert bounded[-1].open_time <= latest[-1].open_time


@pytest.mark.anyio
async def test_binance_kline_websocket_receives_public_1m_update():
    result = await run_binance_kline_websocket_smoke(timeout_seconds=20.0)

    assert result["received"] is True
    assert result["symbol"] == "BTCUSDT"
    assert result["interval"] == "1m"
    assert result["open_time"] > 0


@dataclass
class RecordingKlineStore:
    latest: object = None

    def __post_init__(self):
        self.added = []

    def get_latest_kline(self, name):
        return self.latest

    def add_klines(self, name, klines):
        rows = list(klines)
        self.added.append((name, rows))
        self.latest = rows[-1] if rows else self.latest
        return len(rows)

    def get_latest_klines(self, name, limit):
        rows = []
        for _, batch in self.added:
            rows.extend(batch)
        return rows[-limit:]


class RecordingDb:
    def __init__(self):
        self.kline = RecordingKlineStore()


def _task_config():
    return TaskConfig(
        id=9001,
        ttype=TaskType.TRADER,
        symbol_interval=_symbol_interval(),
        strategies=["macd_triple_divergence"],
        free=1000,
        live_execution_mode="manual_notify",
    )


@pytest.mark.anyio
async def test_realtime_runtime_startup_uses_real_binance_backfill_without_orders(binance_exchange):
    db = RecordingDb()
    strategy_windows = []

    def strategy_runner(candles):
        strategy_windows.append(list(candles))
        return None

    runtime = RealtimeLiveStrategyRuntime(
        _task_config(),
        Config(window=500),
        db_manager=db,
        exchange=binance_exchange,
        strategy_runner=strategy_runner,
    )

    result = await runtime.startup()

    assert result.backfill_plan.limit == 500
    assert runtime.diagnostics["startup_backfill_inserted"] > 0
    assert db.kline.added
    assert len(strategy_windows) == 1
    assert len(strategy_windows[0]) == runtime.diagnostics["startup_backfill_inserted"]


@pytest.mark.skipif(
    not os.environ.get("TRADER_BINANCE_ACCOUNT_SMOKE"),
    reason="requires TRADER_BINANCE_ACCOUNT_SMOKE=1; uses read-only signed account endpoint",
)
def test_binance_signed_account_endpoint_is_reachable_without_printing_balances():
    load_dotenv()
    cfg = new_and_env()
    ex_cfg = parse_exchange_config(cfg.exchange)
    assert ex_cfg.api_key
    assert ex_cfg.api_secret

    client = Spot(
        config_rest_api=ConfigurationRestAPI(
            api_key=ex_cfg.api_key,
            api_secret=ex_cfg.api_secret,
            base_path=SPOT_REST_API_PROD_URL,
            timeout=10000,
            backoff=1,
        )
    )

    account = client.rest_api.get_account(omit_zero_balances=True, recv_window=60000).data()

    assert account is not None
    assert account.account_type
