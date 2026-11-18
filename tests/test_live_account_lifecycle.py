import pytest

from trader.core.exchange.account_lifecycle import (
    InMemoryExchangeAdapter,
    LiveAccountError,
    LiveAccountLifecycle,
    capacity_snapshot,
    operable_amount,
    parse_symbol,
)
from trader.core.exchange.domain import Balance, MarginMode
from trader.core.shared.domain import Symbol


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_capacity_snapshot_adds_max_borrowable_to_free_balance():
    exchange = InMemoryExchangeAdapter(balances={"USDT": 100.0}, max_borrowable={"USDT": 40.0})

    snapshot = capacity_snapshot(exchange, "USDT", symbol="BTCUSDT", requires_borrow=True)

    assert snapshot.balance == 100.0
    assert snapshot.max_borrowable == 40.0
    assert snapshot.operable_capacity == 140.0


def test_capacity_snapshot_skips_borrow_when_precheck_disabled():
    exchange = InMemoryExchangeAdapter(balances={"USDT": 100.0}, max_borrowable={"USDT": 40.0})

    snapshot = capacity_snapshot(exchange, "USDT", requires_borrow=True, borrow_precheck=False)

    assert snapshot.max_borrowable == 0.0
    assert snapshot.operable_capacity == 100.0


def test_operable_amount_uses_free_balance_not_locked():
    balances = [Balance(asset="USDT", free=25.0, locked=75.0)]

    assert operable_amount(balances, "USDT", 10.0) == 35.0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SOLUSDT", "SOLUSDT"),
        ("SOL-USDT", "SOLUSDT"),
        ("sol/usdt", "SOLUSDT"),
        ("ETHBTC", "ETHBTC"),
    ],
)
def test_parse_symbol_requires_explicit_pair(raw, expected):
    symbol = parse_symbol(raw)

    assert symbol is not None
    assert symbol.name() == expected


@pytest.mark.parametrize("raw", ["", "SOL", "USDT"])
def test_parse_symbol_rejects_incomplete_targets(raw):
    assert parse_symbol(raw) is None


def test_preview_and_cancel_open_orders_are_symbol_scoped():
    exchange = InMemoryExchangeAdapter(
        open_orders={
            "SOLUSDT": [{"symbol": "SOLUSDT", "orderId": "1", "side": "BUY", "origQty": "2", "price": "10"}],
            "BTCUSDT": [{"symbol": "BTCUSDT", "orderId": "2", "side": "SELL", "origQty": "1", "price": "20"}],
        }
    )
    symbol = Symbol("SOL-USDT")

    preview = LiveAccountLifecycle.preview_open_orders(exchange, symbol)
    count = LiveAccountLifecycle.cancel_open_orders_for_symbol(exchange, symbol)

    assert [order["order_id"] for order in preview] == ["1"]
    assert count == 1
    assert exchange.cancelled_all == ["SOLUSDT"]


@pytest.mark.anyio
async def test_task_scoped_cleanup_cancels_only_persisted_task_orders():
    exchange = InMemoryExchangeAdapter()
    lifecycle = LiveAccountLifecycle()
    seen: set[tuple[int, str]] = set()

    class Record:
        symbol = "SOL-USDT"
        exchange_order_id = "order-9"
        raw_payload = {}

    canceled = []

    async def on_canceled(record):
        canceled.append(record.exchange_order_id)

    result = await lifecycle.cancel_task_open_orders(
        7,
        exchange,
        reason="task_closed",
        records=[Record()],
        seen=seen,
        on_canceled=on_canceled,
    )

    assert result is True
    assert exchange.cancelled == [("SOLUSDT", "order-9")]
    assert canceled == ["order-9"]


@pytest.mark.anyio
async def test_task_scoped_cleanup_falls_back_to_fallback_symbols_without_records():
    exchange = InMemoryExchangeAdapter()
    lifecycle = LiveAccountLifecycle()

    result = await lifecycle.cancel_task_open_orders(
        None,
        exchange,
        reason="task_closed",
        fallback_symbols=[Symbol("SOL-USDT")],
    )

    assert result is False
    assert exchange.cancelled_all == ["SOLUSDT"]


def test_credential_context_requires_credential():
    with pytest.raises(LiveAccountError, match="missing BINANCE API credential"):
        LiveAccountLifecycle.build_credential_context(
            base_cfg=None,
            service_key="secret",
            credential=None,
            user_id=7,
            margin_mode=MarginMode.SPOT,
        )


def test_parse_symbol_accepts_wider_quote_asset_list():
    assert parse_symbol("BTCTUSD").name() == "BTCTUSD"
    assert parse_symbol("ETHDAI").name() == "ETHDAI"


@pytest.mark.anyio
async def test_task_scoped_cleanup_fires_on_canceled_once_per_record_even_with_many_orders():
    exchange = InMemoryExchangeAdapter()
    lifecycle = LiveAccountLifecycle()
    seen: set[tuple[int, str]] = set()

    class Record:
        symbol = "SOL-USDT"
        exchange_order_id = "order-1,order-2"
        raw_payload = {}

    canceled = []

    async def on_canceled(record):
        canceled.append(record.exchange_order_id)

    result = await lifecycle.cancel_task_open_orders(
        7,
        exchange,
        reason="task_closed",
        records=[Record()],
        seen=seen,
        on_canceled=on_canceled,
    )

    assert result is True
    assert exchange.cancelled == [("SOLUSDT", "order-1"), ("SOLUSDT", "order-2")]
    assert canceled == ["order-1,order-2"]
