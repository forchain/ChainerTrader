import asyncio
from types import SimpleNamespace

import pytest
from tortoise import Tortoise

from trader.common.config import Config
from trader.common.logger import Logger
from trader.database.account_fund_reservation import AccountFundReservationCol, FundReservationError
from trader.database.config import build_tortoise_config
from trader.execution.models import ExecutionStatus, GatewayMode
from trader.execution.state import ExecutionStateRecord
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig, parse_task_config
from trader.task.task_manager import TaskManager
from trader.task.task_type import TaskType
from trader.task.trader_task import TraderTask
from trader.utils.symbol_interval import Interval, SymbolInterval


class _Log:
    def debug(self, *_args, **_kwargs):
        pass

    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


class _Exchange:
    def __init__(self, quote_balance=100.0, quote_borrowable=0.0, name="BINANCE"):
        self.quote_balance = quote_balance
        self.quote_borrowable = quote_borrowable
        self._name = name
        self.balance_reads = []
        self.borrowable_reads = []

    def name(self):
        return self._name

    def get_account_balance(self, asset):
        self.balance_reads.append(asset)
        if asset == "USDT":
            return self.quote_balance
        return 0.0

    def get_max_borrowable(self, asset, symbol=None):
        self.borrowable_reads.append((asset, symbol))
        if asset == "USDT":
            return {"amount": self.quote_borrowable, "symbol": symbol}
        return {"amount": 0.0, "symbol": symbol}


class _CaptureLogger:
    def __init__(self):
        self.errors = []
        self.infos = []
        self.warnings = []

    def debug(self, *_args, **_kwargs):
        pass

    def info(self, message, *_args, **_kwargs):
        self.infos.append(str(message))

    def warning(self, message, *_args, **_kwargs):
        self.warnings.append(str(message))

    def error(self, message, *_args, **_kwargs):
        self.errors.append(str(message))


async def _with_db(fn):
    await Tortoise.init(config=build_tortoise_config("sqlite://:memory:"))
    await Tortoise.generate_schemas()
    try:
        await fn()
    finally:
        await Tortoise.close_connections()


def test_account_fund_reservation_rejects_over_capacity_and_releases():
    async def run():
        store = AccountFundReservationCol(_Log())

        first = await store.reserve(
            account_key="BINANCE:credential:1",
            exchange="BINANCE",
            credential_id=1,
            user_id=7,
            task_id=101,
            asset="USDT",
            amount=60.0,
            capacity=100.0,
            reason="live_task_start",
        )
        assert first.created is True
        assert await store.active_reserved_amount("BINANCE:credential:1", "USDT") == 60.0

        with pytest.raises(FundReservationError, match="insufficient reserved capacity"):
            await store.reserve(
                account_key="BINANCE:credential:1",
                exchange="BINANCE",
                credential_id=1,
                user_id=7,
                task_id=102,
                asset="USDT",
                amount=50.0,
                capacity=100.0,
                reason="live_task_start",
            )

        assert await store.release_task(101, reason="task_done") == 1
        assert await store.active_reserved_amount("BINANCE:credential:1", "USDT") == 0.0

        second = await store.reserve(
            account_key="BINANCE:credential:1",
            exchange="BINANCE",
            credential_id=1,
            user_id=7,
            task_id=102,
            asset="USDT",
            amount=50.0,
            capacity=100.0,
            reason="live_task_start",
        )
        assert second.created is True
        assert await store.remaining_for_task(102, "USDT") == 50.0

    asyncio.run(_with_db(run))


def test_account_fund_reservation_tracks_spent_budget():
    async def run():
        store = AccountFundReservationCol(_Log())
        await store.reserve(
            account_key="BINANCE:credential:1",
            exchange="BINANCE",
            credential_id=1,
            user_id=7,
            task_id=101,
            asset="USDT",
            amount=60.0,
            capacity=100.0,
            reason="live_task_start",
        )

        await store.mark_spent(101, "USDT", 25.0)

        assert await store.remaining_for_task(101, "USDT") == 35.0

    asyncio.run(_with_db(run))


def test_task_manager_reserves_live_task_budget_before_start_and_releases_on_completion():
    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = Logger(cfg)
        reservation_store = AccountFundReservationCol(_Log())

        async def add_tasks(_states):
            return len(_states)

        db_manager = SimpleNamespace(task=SimpleNamespace(add_tasks=add_tasks), account_fund_reservation=reservation_store)
        manager = TaskManager(cfg, logger, db_manager, _Exchange(quote_balance=100.0))
        task_config = TaskConfig(
            id=201,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            free=40.0,
            live_execution_mode="auto_trade",
        )

        async def fake_add_task(taskc, queue):
            task = BaseTask(taskc, cfg, logger, db_manager, manager.exchange)
            manager.tasks[task.id()] = task
            await task.start(queue)

        manager.add_task = fake_add_task

        await manager.do_add_tasks([task_config], asyncio.Queue())

        assert await reservation_store.active_reserved_amount("BINANCE:default", "USDT") == 0.0

    asyncio.run(_with_db(run))


def test_task_manager_accepts_multiple_live_tasks_when_each_fits_exchange_balance():
    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = Logger(cfg)
        reservation_store = AccountFundReservationCol(_Log())
        started = []

        async def add_tasks(_states):
            return len(_states)

        db_manager = SimpleNamespace(task=SimpleNamespace(add_tasks=add_tasks), account_fund_reservation=reservation_store)
        manager = TaskManager(cfg, logger, db_manager, _Exchange(quote_balance=100.0))
        first = TaskConfig(
            id=301,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            free=100.0,
            live_execution_mode="auto_trade",
        )
        second = TaskConfig(
            id=302,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("ETH-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            free=100.0,
            live_execution_mode="auto_trade",
        )

        async def fake_add_task(taskc, _queue):
            started.append(taskc.id)

        manager.add_task = fake_add_task

        await manager.do_add_tasks([first, second], asyncio.Queue())

        assert started == [301, 302]
        assert first.fund_reservation_amount == 100.0
        assert first.fund_reservation_remaining == 100.0
        assert second.fund_reservation_amount == 100.0
        assert second.fund_reservation_remaining == 100.0

        assert await reservation_store.active_reserved_amount("BINANCE:default", "USDT") == 0.0

    asyncio.run(_with_db(run))


def test_task_manager_rejects_first_live_task_that_exceeds_its_account_capacity():
    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = _CaptureLogger()
        started = []

        async def add_tasks(_states):
            return len(_states)

        db_manager = SimpleNamespace(task=SimpleNamespace(add_tasks=add_tasks), account_fund_reservation=None)
        manager = TaskManager(cfg, logger, db_manager, _Exchange(quote_balance=5000.0))
        first = TaskConfig(
            id=311,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            free=1000.0,
            live_execution_mode="auto_trade",
        )
        second = TaskConfig(
            id=312,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("ETH-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            free=10000.0,
            live_execution_mode="auto_trade",
        )

        async def fake_add_task(taskc, _queue):
            started.append(taskc.id)

        manager.add_task = fake_add_task

        with pytest.raises(FundReservationError) as exc_info:
            await manager.do_add_tasks([first, second], asyncio.Queue())

        assert started == []
        assert "task_id=312" in str(exc_info.value)
        assert "requested=10000.0" in str(exc_info.value)
        assert "capacity=5000.0" in str(exc_info.value)
        assert any("task_id=312" in line and "symbol=ETHUSDT" in line for line in logger.errors)

    asyncio.run(run())


def test_task_manager_rejects_live_task_budget_without_reservation_store():
    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = Logger(cfg)
        db_manager = SimpleNamespace(task=None, account_fund_reservation=None)
        manager = TaskManager(cfg, logger, db_manager, _Exchange(quote_balance=50.0))
        task_config = TaskConfig(
            id=351,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            free=10000.0,
            live_execution_mode="auto_trade",
        )
        manager.add_task = lambda _taskc, _queue: asyncio.sleep(0)

        with pytest.raises(FundReservationError, match="insufficient live task balance"):
            await manager.do_add_tasks([task_config], asyncio.Queue())

    asyncio.run(run())


def test_task_manager_accepts_cross_margin_budget_when_borrowable_capacity_covers_shortfall():
    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = Logger(cfg)
        db_manager = SimpleNamespace(task=None, account_fund_reservation=None)
        manager = TaskManager(cfg, logger, db_manager, _Exchange(quote_balance=0.08, quote_borrowable=12000.0))
        task_config = TaskConfig(
            id=355,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            strategy_params={"chainer_mode": "BOTH"},
            free=10000.0,
            live_execution_mode="auto_trade",
        )
        manager.add_task = lambda _taskc, _queue: asyncio.sleep(0)

        await manager.do_add_tasks([task_config], asyncio.Queue())

        assert task_config.fund_reservation_amount == 10000.0
        assert task_config.fund_reservation_remaining == 10000.0

    asyncio.run(run())


def test_task_manager_preflights_mixed_live_tasks_against_their_routed_accounts():
    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = Logger(cfg)
        spot_exchange = _Exchange(quote_balance=100.0, name="SPOT")
        margin_exchange = _Exchange(quote_balance=10.0, quote_borrowable=90.0, name="MARGIN")
        db_manager = SimpleNamespace(task=None, account_fund_reservation=None)
        manager = TaskManager(cfg, logger, db_manager, spot_exchange)
        long_task = TaskConfig(
            id=361,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            free=100.0,
            live_execution_mode="auto_trade",
        )
        short_task = TaskConfig(
            id=362,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("ETH-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            strategy_params={"chainer_mode": "BOTH"},
            free=100.0,
            live_execution_mode="auto_trade",
        )

        async def exchange_for_task(task_cfg):
            if task_cfg.id == 362:
                return margin_exchange
            return spot_exchange

        manager._exchange_for_task = exchange_for_task
        manager.add_task = lambda _taskc, _queue: asyncio.sleep(0)

        await manager.do_add_tasks([long_task, short_task], asyncio.Queue())

        assert spot_exchange.balance_reads == ["USDT"]
        assert spot_exchange.borrowable_reads == []
        assert margin_exchange.balance_reads == ["USDT"]
        assert margin_exchange.borrowable_reads == [("USDT", "ETHUSDT")]
        assert long_task.fund_reservation_amount == 100.0
        assert short_task.fund_reservation_amount == 100.0

    asyncio.run(run())


def test_task_manager_rejects_cross_margin_budget_when_balance_plus_borrowable_is_insufficient():
    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = Logger(cfg)
        db_manager = SimpleNamespace(task=None, account_fund_reservation=None)
        manager = TaskManager(cfg, logger, db_manager, _Exchange(quote_balance=0.08, quote_borrowable=5000.0))
        task_config = TaskConfig(
            id=356,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            strategy_params={"chainer_mode": "BOTH"},
            free=10000.0,
            live_execution_mode="auto_trade",
        )
        manager.add_task = lambda _taskc, _queue: asyncio.sleep(0)

        with pytest.raises(FundReservationError) as exc_info:
            await manager.do_add_tasks([task_config], asyncio.Queue())

        assert "insufficient live task balance" in str(exc_info.value)
        assert "capacity=5000.08" in str(exc_info.value)
        assert "balance=0.08" in str(exc_info.value)
        assert "max_borrowable=5000.0" in str(exc_info.value)
        assert "operable_capacity=5000.08" in str(exc_info.value)
        assert "requested=10000.0" in str(exc_info.value)

    asyncio.run(run())


def test_task_manager_preflights_parsed_uncapped_auto_trade_against_task_free_budget():
    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = Logger(cfg)
        db_manager = SimpleNamespace(task=None, account_fund_reservation=None)
        manager = TaskManager(cfg, logger, db_manager, _Exchange(quote_balance=50.0, quote_borrowable=0.0))
        task_config = parse_task_config(
            """
            [
              {
                "task_type": "TRADER",
                "symbol": "BTC-USDT",
                "interval": "1m",
                "strategy": "macd_triple_divergence",
                "free": 10000,
                "manual_start_position": 0,
                "live_execution_mode": "auto_trade",
                "strategy_params": {
                  "chainer_mode": "BOTH"
                }
              }
            ]
            """
        )[0]
        manager.add_task = lambda _taskc, _queue: asyncio.sleep(0)

        with pytest.raises(FundReservationError) as exc_info:
            await manager.do_add_tasks([task_config], asyncio.Queue())

        assert task_config.live_trade_max_notional == 0.0
        assert "capacity=50.0" in str(exc_info.value)
        assert "requested=10000.0" in str(exc_info.value)

    asyncio.run(run())


def test_task_manager_logs_balance_plus_borrowable_rejection_reason():
    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = _CaptureLogger()
        db_manager = SimpleNamespace(task=None, account_fund_reservation=None)
        manager = TaskManager(cfg, logger, db_manager, _Exchange(quote_balance=0.08, quote_borrowable=5000.0))
        task_config = TaskConfig(
            id=358,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            strategy_params={"chainer_mode": "BOTH"},
            free=10000.0,
            live_execution_mode="auto_trade",
        )
        manager.add_task = lambda _taskc, _queue: asyncio.sleep(0)

        with pytest.raises(FundReservationError):
            await manager.do_add_tasks([task_config], asyncio.Queue())

        rejection_log = "\n".join(logger.errors)
        assert "strategy rejected before execution" in rejection_log
        assert "rule=requested <= operable_capacity" in rejection_log
        assert "symbol=BTCUSDT" in rejection_log
        assert "required=10000.0" in rejection_log
        assert "balance=0.08" in rejection_log
        assert "max_borrowable=5000.0" in rejection_log
        assert "operable_capacity=5000.08" in rejection_log
        assert "insufficient live task balance" in rejection_log

    asyncio.run(run())


def test_task_manager_uses_current_max_borrowable_amount_not_account_borrow_limit_for_margin_capacity():
    class _ExchangeWithLargeBorrowLimit(_Exchange):
        def get_max_borrowable(self, asset, symbol=None):
            if asset == "USDT":
                return {"amount": "22.89384497", "borrowLimit": "100000", "symbol": symbol}
            return {"amount": "0", "borrowLimit": "0", "symbol": symbol}

    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = Logger(cfg)
        db_manager = SimpleNamespace(task=None, account_fund_reservation=None)
        manager = TaskManager(cfg, logger, db_manager, _ExchangeWithLargeBorrowLimit(quote_balance=5.81213216))
        task_config = TaskConfig(
            id=357,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            strategy_params={"chainer_mode": "BOTH"},
            free=30.0,
            live_execution_mode="auto_trade",
        )
        manager.add_task = lambda _taskc, _queue: asyncio.sleep(0)

        with pytest.raises(FundReservationError) as exc_info:
            await manager.do_add_tasks([task_config], asyncio.Queue())

        assert "capacity=28.70597713" in str(exc_info.value)
        assert "requested=30.0" in str(exc_info.value)

    asyncio.run(run())


def test_task_manager_recovers_live_task_without_fresh_balance_preflight():
    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = Logger(cfg)
        db_manager = SimpleNamespace(task=None, account_fund_reservation=None)
        manager = TaskManager(cfg, logger, db_manager, _Exchange(quote_balance=50.0))
        task_config = TaskConfig(
            id=352,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            free=10000.0,
            live_execution_mode="auto_trade",
        )
        manager._build_task = lambda task_cfg, exchange: BaseTask(task_cfg, cfg, logger, db_manager, exchange)

        await manager.recover_task(task_config, asyncio.Queue())

        assert task_config.id in manager.tasks
        assert task_config.fund_reservation_amount == 10000.0
        assert task_config.fund_reservation_remaining == 10000.0

    asyncio.run(run())


def test_task_manager_reconstructs_recovered_runtime_budget_from_execution_records():
    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = Logger(cfg)
        records = [
            ExecutionStateRecord(
                task_id=359,
                idempotency_key="entry-1",
                intent_id="intent-1",
                operation_id="op-1",
                gateway=GatewayMode.BINANCE_LIVE,
                staged_execution_mode="auto_trade",
                symbol="BTCUSDT",
                order_role="entry",
                status=ExecutionStatus.SUBMITTED,
                quantity=0.2,
                price=100.0,
            ),
            ExecutionStateRecord(
                task_id=359,
                idempotency_key="entry-2",
                intent_id="intent-2",
                operation_id="op-2",
                gateway=GatewayMode.BINANCE_LIVE,
                staged_execution_mode="auto_trade",
                symbol="BTCUSDT",
                order_role="entry",
                status=ExecutionStatus.SUBMITTED,
                quantity=0.2,
                price=100.0,
            ),
        ]

        class _ExecutionStateStore:
            async def list_open_by_task(self, task_id):
                assert task_id == 359
                return records

        db_manager = SimpleNamespace(task=None, execution_state=_ExecutionStateStore(), account_fund_reservation=None)
        manager = TaskManager(cfg, logger, db_manager, _Exchange(quote_balance=0.0))
        task_config = TaskConfig(
            id=359,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            free=100.0,
            live_execution_mode="auto_trade",
        )
        manager._build_task = lambda task_cfg, exchange: BaseTask(task_cfg, cfg, logger, db_manager, exchange)

        await manager.recover_task(task_config, asyncio.Queue())

        assert task_config.fund_reservation_amount == 100.0
        assert task_config.fund_reservation_remaining == 60.0

    asyncio.run(run())


def test_task_manager_recovery_build_failure_does_not_create_live_reservation():
    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = Logger(cfg)
        reservation_store = AccountFundReservationCol(_Log())
        db_manager = SimpleNamespace(task=None, account_fund_reservation=reservation_store)
        manager = TaskManager(cfg, logger, db_manager, _Exchange(quote_balance=100.0))
        task_config = TaskConfig(
            id=353,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            free=40.0,
            live_execution_mode="auto_trade",
        )
        manager._build_task = lambda _task_cfg, _exchange: None

        await manager.recover_task(task_config, asyncio.Queue())

        assert await reservation_store.active_reserved_amount("BINANCE:default", "USDT") == 0.0

    asyncio.run(_with_db(run))


def test_task_manager_exits_cli_when_live_task_budget_preflight_fails():
    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = Logger(cfg)
        db_manager = SimpleNamespace(task=None, account_fund_reservation=None)
        manager = TaskManager(cfg, logger, db_manager, _Exchange(quote_balance=50.0))
        task_config = TaskConfig(
            id=354,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            free=10000.0,
            live_execution_mode="auto_trade",
        )
        queue = asyncio.Queue()

        manager.add_tasks([task_config], queue)
        msg = await asyncio.wait_for(queue.get(), timeout=1)

        assert msg.is_exit()
        assert task_config.id not in manager.tasks

    asyncio.run(run())


def test_trader_task_persists_auto_execution_spent_budget():
    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = Logger(cfg)
        reservation_store = AccountFundReservationCol(_Log())
        await reservation_store.reserve(
            account_key="BINANCE:default",
            exchange="BINANCE",
            credential_id=None,
            user_id=None,
            task_id=401,
            asset="USDT",
            amount=50.0,
            capacity=100.0,
            reason="live_task_start",
        )

        async def add_tasks(_states):
            return len(_states)

        db_manager = SimpleNamespace(
            task=SimpleNamespace(add_tasks=add_tasks),
            execution_state=None,
            account_fund_reservation=reservation_store,
        )
        task_config = TaskConfig(
            id=401,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            free=50.0,
            live_execution_mode="auto_trade",
        )
        task_config.fund_reservation_amount = 50.0
        task_config.fund_reservation_asset = "USDT"
        task = TraderTask(task_config, cfg, logger, db_manager, _Exchange(quote_balance=100.0))
        outcome = SimpleNamespace(status="submitted", effective_notional=30.0, execution_state_records=[])

        await task._persist_auto_execution_state(outcome)

        assert await reservation_store.remaining_for_task(401, "USDT") == 20.0

    asyncio.run(_with_db(run))


def test_task_manager_shutdown_preserves_running_live_task_reservation_for_recovery():
    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = Logger(cfg)
        reservation_store = AccountFundReservationCol(_Log())
        saved_batches = []

        async def add_tasks(states):
            saved_batches.append([state.to_dict() for state in states])
            return len(states)

        class _LongRunningTask(BaseTask):
            async def start(self, queue):
                await super().start(queue)
                await self.quit.wait()

        db_manager = SimpleNamespace(task=SimpleNamespace(add_tasks=add_tasks), account_fund_reservation=reservation_store)
        manager = TaskManager(cfg, logger, db_manager, _Exchange(quote_balance=100.0))
        task_config = TaskConfig(
            id=501,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            free=40.0,
            live_execution_mode="auto_trade",
        )
        manager._build_task = lambda task_cfg, exchange: _LongRunningTask(task_cfg, cfg, logger, db_manager, exchange)

        manager.add_tasks([task_config], asyncio.Queue())
        while task_config.id not in manager.tasks:
            await asyncio.sleep(0)

        await manager.close()

        assert manager.tasks[task_config.id].ts.state.name == "RUNNING"
        assert await reservation_store.active_reserved_amount("BINANCE:default", "USDT") == 0.0

    asyncio.run(_with_db(run))


def test_task_manager_releases_live_reservation_when_failed_state_persistence_fails():
    async def run():
        cfg = Config(tasks="[]", cash=1000.0)
        logger = Logger(cfg)
        reservation_store = AccountFundReservationCol(_Log())

        class _FailingTaskRepo:
            async def add_tasks(self, _states):
                raise RuntimeError("task state write failed")

        db_manager = SimpleNamespace(task=_FailingTaskRepo(), account_fund_reservation=reservation_store)
        manager = TaskManager(cfg, logger, db_manager, _Exchange(quote_balance=100.0))
        task_config = TaskConfig(
            id=502,
            ttype=TaskType.TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval("1m")),
            strategies=["macd_triple_divergence"],
            free=40.0,
            live_execution_mode="auto_trade",
        )

        async def fail_add_task(_taskc, _queue):
            raise RuntimeError("task startup failed")

        manager.add_task = fail_add_task

        with pytest.raises(RuntimeError, match="task state write failed"):
            await manager.do_add_tasks([task_config], asyncio.Queue())

        assert await reservation_store.active_reserved_amount("BINANCE:default", "USDT") == 0.0

    asyncio.run(_with_db(run))
