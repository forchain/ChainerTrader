from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.persistence_harness import InMemoryExecutionStateStore, InMemoryTaskRepository
from trader.adapters.outbound.backtrader.live_trader_runner import LiveTraderTaskRunner
from trader.adapters.outbound.notification.execution_gateway import NotificationOnlyExecutionGateway
from trader.core.execution import ExecutionGateway, ExecutionStateRecord, ExecutionStatus, GatewayMode
from trader.core.shared.domain import Interval, Kline, Operate, OperateType, SymbolInterval
from trader.core.task import TaskConfig, TaskRunner, TaskType

BASE = 1_700_000_000


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _DummyLog:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass

    def debug(self, *_args, **_kwargs):
        pass


class _FakeKlineRepo:
    def __init__(self, klines: list[Kline]):
        self.klines = list(klines)

    async def get_latest_kline(self, _name: str) -> Kline | None:
        return self.klines[-1] if self.klines else None

    async def get_latest_klines(self, _name: str, limit: int) -> list[Kline]:
        return self.klines[-limit:]

    async def add_klines(self, _name: str, klines: list[Kline], **_kwargs) -> int:
        self.klines.extend(klines)
        return len(klines)


class _FakeExchangeClient:
    def __init__(self, klines: list[Kline]):
        self.klines = klines
        self.orders: list[tuple] = []
        self.margin_mode = SimpleNamespace(name="SPOT", value="spot")

    def name(self) -> str:
        return "BINANCE"

    def get_account_commission(self, _symbol: str) -> float:
        return 0.001

    def get_account_balance(self, _asset: str) -> float:
        return 1000.0

    def get_latest_klines(self, _si, _limit: int) -> list[Kline]:
        return list(self.klines)

    def get_klines(self, _si, **_kwargs) -> list[Kline]:
        return list(self.klines)

    def new_order(self, symbol, op, quantity):
        self.orders.append((symbol.name(), op, quantity))
        return {"orderId": "ord-live-1"}


class _FakeSubscription:
    def __init__(self, updates: list[Any], quit_event: asyncio.Event):
        self._updates = list(updates)
        self._quit_event = quit_event
        self.unsubscribed = False

    async def get(self):
        if self._updates:
            item = self._updates.pop(0)
            if not self._updates:
                self._quit_event.set()
            return item
        self._quit_event.set()
        await asyncio.sleep(0)
        raise asyncio.TimeoutError

    async def unsubscribe(self):
        self.unsubscribed = True


class _FakeMarketStream:
    def __init__(self, updates: list[Any], quit_event: asyncio.Event):
        self.updates = updates
        self.quit_event = quit_event
        self.connector = None

    async def subscribe(self, _key, reconnect_callback=None):
        return _FakeSubscription(self.updates, self.quit_event)

    def status(self, _key):
        return SimpleNamespace(state=SimpleNamespace(value="connected"), subscriber_count=1, last_error=None)


class _FakeReservationStore:
    def __init__(self):
        self.spent_calls: list[tuple[int, str, float]] = []

    async def mark_spent(self, task_id: int, asset: str, amount: float):
        self.spent_calls.append((task_id, asset, amount))


class _FakeEventPublisher:
    def __init__(self):
        self.events: list[Any] = []

    async def publish(self, event):
        self.events.append(event)


def _kline(open_time: int, close: float = 100.0) -> Kline:
    return Kline(
        open_time=open_time,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        close_time=open_time + 59,
        volume=10.0,
        vol_quote=1000.0,
        trades=5,
        vol_taker_base=5.0,
        vol_taker_quote=500.0,
        ignore=0.0,
    )


def _update(open_time: int, *, closed: bool = True, close: float = 105.0):
    return SimpleNamespace(
        symbol="BTCUSDT",
        interval="1m",
        open_time=open_time,
        close_time=open_time + 59,
        event_time=open_time + 59,
        is_closed=closed,
        close=close,
        volume=12.0,
        to_kline=lambda: _kline(open_time, close=close),
        to_chart_candle=lambda: {"time": open_time, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 12.0},
    )


@pytest.mark.anyio
async def test_live_trader_runner_manual_notify_never_places_orders_and_emits_events():
    quit_event = asyncio.Event()
    task_repo = InMemoryTaskRepository()
    kline_repo = _FakeKlineRepo([_kline(BASE), _kline(BASE + 60)])
    exchange = _FakeExchangeClient([_kline(BASE), _kline(BASE + 60)])
    publisher = _FakeEventPublisher()
    sent_notifications = []

    class _FakeSender:
        notice_type = "MAIL_TEST"
        recipient = "ops@example.com"

        def send(self, content: str, title: str = "Trader"):
            sent_notifications.append((title, content))
            return None

    class _FakeBtRunner:
        def __init__(self, _strategy, *, operation_handler=None, **_kwargs):
            self.operation_handler = operation_handler

        def start(self, warmup=None):
            pass

        def put_kline(self, kline):
            op = Operate(OperateType.BUY, kline.open_time, kline.close)
            op.feed_phase = "live"
            self.operation_handler(op)
            return True

        def status(self):
            return {"feed_phase": "live"}

        def stop(self):
            pass

    tcfg = TaskConfig(
        91,
        TaskType.TRADER,
        SymbolInterval("BTC-USDT", Interval.INTERVAL_1m),
        strategies=["macd_triple_divergence"],
        free=500.0,
        live_execution_mode="manual_notify",
    )
    cfg = SimpleNamespace(cash=1000.0, commission=0.001, window=500, warmup_candles=500, mode="NORMAL", period=14)
    queue: asyncio.Queue = asyncio.Queue()
    runner = LiveTraderTaskRunner(
        cfg=cfg,
        log=_DummyLog(),
        exchange_client=exchange,
        execution_gateway=NotificationOnlyExecutionGateway(staged_execution_mode="manual_notify"),
        task_repository=task_repo,
        kline_repository=kline_repo,
        market_stream=_FakeMarketStream([_update(BASE + 120)], quit_event),
        event_publisher=publisher,
        notification_sender=_FakeSender(),
        live_runner_factory=_FakeBtRunner,
        strategy_parser=lambda _names: ["NoopStrategy"],
    )
    assert isinstance(runner, TaskRunner)

    ts = await runner.run(tcfg, queue=queue, quit_event=quit_event)

    assert exchange.orders == []
    assert any(ev.event_type == "notification" for ev in publisher.events)
    assert any(ev.event_type == "strategy_execution" for ev in publisher.events)
    assert len(sent_notifications) == 1
    assert ts.tret is not None and len(ts.tret.opts) == 1
    assert (await task_repo.get_task(91)) is not None


@pytest.mark.anyio
async def test_live_trader_runner_auto_trade_reconciles_executes_and_tracks_budget():
    quit_event = asyncio.Event()
    task_repo = InMemoryTaskRepository()
    exec_store = InMemoryExecutionStateStore()
    await exec_store.save(
        ExecutionStateRecord(
            idempotency_key="task:92:prior",
            intent_id="intent-prior",
            operation_id="op-prior",
            gateway=GatewayMode.BINANCE_LIVE,
            staged_execution_mode="auto_trade",
            symbol="BTCUSDT",
            order_role="entry",
            status=ExecutionStatus.SUBMITTED,
            task_id=92,
            exchange_order_id="prior-1",
            quantity=0.01,
            price=100.0,
        )
    )
    reservation_store = _FakeReservationStore()
    kline_repo = _FakeKlineRepo([_kline(BASE), _kline(BASE + 60)])
    exchange = _FakeExchangeClient([_kline(BASE), _kline(BASE + 60)])
    publisher = _FakeEventPublisher()

    class _FakeGateway(ExecutionGateway):
        def __init__(self):
            self.opened = []

        @property
        def capabilities(self):
            from trader.core.execution import GatewayCapabilities, GatewayCapability

            return GatewayCapabilities(gateway=GatewayMode.BINANCE_LIVE, supported={GatewayCapability.MARKET_ENTRY})

        def open_position(self, intent):
            from trader.core.execution import ExecutionEvent, ExecutionResult

            self.opened.append(intent.symbol)
            ev = ExecutionEvent.order_accepted(
                gateway=GatewayMode.BINANCE_LIVE,
                staged_execution_mode="auto_trade",
                intent_id=intent.intent_id,
                operation_id=intent.operation_id,
                symbol=intent.symbol,
                order_id="gw-ord-1",
            )
            return ExecutionResult.from_accepted(
                intent_id=intent.intent_id,
                operation_id=intent.operation_id,
                status=ExecutionStatus.SUBMITTED,
                events=[ev],
                gateway_order_id="gw-ord-1",
            )

        def place_protection(self, intent):
            raise NotImplementedError

        def replace_protection(self, intent):
            raise NotImplementedError

        def close_position(self, intent):
            raise NotImplementedError

        def cancel_order(self, intent):
            raise NotImplementedError

        def reconcile(self, request):
            raise NotImplementedError

    class _FakeBtRunner:
        def __init__(self, _strategy, *, operation_handler=None, **_kwargs):
            self.operation_handler = operation_handler

        def start(self, warmup=None):
            pass

        def put_kline(self, kline):
            op = Operate(OperateType.BUY, kline.open_time, kline.close)
            op.feed_phase = "live"
            op.signal_event_id = "sig-92-1"
            self.operation_handler(op)
            return True

        def status(self):
            return {"feed_phase": "live"}

        def stop(self):
            pass

    gateway = _FakeGateway()
    tcfg = TaskConfig(
        92,
        TaskType.TRADER,
        SymbolInterval("BTC-USDT", Interval.INTERVAL_1m),
        strategies=["macd_triple_divergence"],
        free=100.0,
        live_execution_mode="auto_trade",
        live_trade_max_notional=100.0,
        fund_reservation_asset="USDT",
        fund_reservation_amount=100.0,
        fund_reservation_remaining=100.0,
    )
    cfg = SimpleNamespace(cash=1000.0, commission=0.001, window=500, warmup_candles=500, mode="NORMAL", period=14)
    runner = LiveTraderTaskRunner(
        cfg=cfg,
        log=_DummyLog(),
        exchange_client=exchange,
        execution_gateway=gateway,
        execution_state_store=exec_store,
        task_repository=task_repo,
        kline_repository=kline_repo,
        fund_reservation_store=reservation_store,
        market_stream=_FakeMarketStream([_update(BASE + 120)], quit_event),
        event_publisher=publisher,
        live_runner_factory=_FakeBtRunner,
        strategy_parser=lambda _names: ["NoopStrategy"],
    )

    ts = await runner.run(tcfg, queue=asyncio.Queue(), quit_event=quit_event)

    assert len(ts.execution_reconcile) == 1
    assert ts.execution_reconcile[0]["exchange_order_id"] == "prior-1"
    assert gateway.opened == ["BTCUSDT"]
    assert reservation_store.spent_calls and reservation_store.spent_calls[0][0] == 92
    assert any(ev.event_type == "auto_execution_outcome" for ev in publisher.events)


def test_live_trader_runner_depends_only_on_ports_not_concrete_db_or_exchange():
    path = Path(__file__).resolve().parents[1] / "src" / "trader" / "adapters" / "outbound" / "backtrader" / "live_trader_runner.py"
    source = path.read_text(encoding="utf-8")
    assert "DatabaseManager" not in source
    assert "BinanceExchange" not in source
    assert "GLOBAL_LIVE_EVENT_BUS" not in source
    assert "GLOBAL_MARKET_STREAM_HUB" not in source
