import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from trader.auth.credentials import encrypt_secret
from trader.common.config import Config
from trader.common.logger import Logger
from trader.exchange.exchange_config import ExchangeConfig, MarginMode
from trader.task.task_config import TaskConfig
from trader.task.task_manager import TaskManager
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import Interval, SymbolInterval
from trader.utils.task_state import TaskState


class _FakeExchange:
    def __init__(self, cfg: ExchangeConfig):
        self.cfg = cfg
        self.margin_mode = cfg.margin_mode


class _CaptureLog:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(str(message))


def _live_task(user_id: int = 7, *, chainer_mode: str | None = None) -> TaskConfig:
    return TaskConfig(
        id=1,
        ttype=TaskType.TRADER,
        symbol_interval=SymbolInterval("BTC-USDT", Interval("1h")),
        strategies=["macd_triple_divergence"],
        strategy_params={"chainer_mode": chainer_mode} if chainer_mode else {},
        user_id=user_id,
    )


def test_user_live_exchange_routing_decrypts_async_user_credentials(monkeypatch):
    async def run():
        created_configs = []

        class FakeBinanceExchange(_FakeExchange):
            def __init__(self, cfg: ExchangeConfig, _log):
                super().__init__(cfg)
                created_configs.append(cfg)

        service_key = "dev-service-secret"
        credential = SimpleNamespace(
            encrypted_api_key=encrypt_secret(service_key, "user-api-key"),
            encrypted_api_secret=encrypt_secret(service_key, "user-api-secret"),
        )

        async def get_default(user_id, exchange):
            await asyncio.sleep(0)
            assert user_id == 7
            assert exchange == "BINANCE"
            return credential

        monkeypatch.setattr("trader.task.task_manager.BinanceExchange", FakeBinanceExchange)
        cfg = Config(tasks="[]", secret_key=service_key)
        base_exchange = _FakeExchange(ExchangeConfig(api_key="base-key", api_secret="base-secret"))
        manager = TaskManager(
            cfg,
            Logger(cfg),
            SimpleNamespace(exchange_credential=SimpleNamespace(get_default=get_default)),
            base_exchange,
        )
        task = _live_task()

        await manager._ensure_routed_exchanges([task])
        routed = await manager._exchange_for_task(task)

        assert routed.cfg.api_key == "user-api-key"
        assert routed.cfg.api_secret == "user-api-secret"
        assert routed.cfg.margin_mode == MarginMode.SPOT
        assert created_configs
        assert all(created.api_key == "user-api-key" for created in created_configs)
        assert all(created.api_secret == "user-api-secret" for created in created_configs)

    asyncio.run(run())


def test_user_live_exchange_routing_logs_target_and_actual_margin_mode(monkeypatch):
    async def run():
        class FakeBinanceExchange(_FakeExchange):
            def __init__(self, cfg: ExchangeConfig, _log):
                super().__init__(cfg)

        service_key = "dev-service-secret"
        credential = SimpleNamespace(
            encrypted_api_key=encrypt_secret(service_key, "user-api-key"),
            encrypted_api_secret=encrypt_secret(service_key, "user-api-secret"),
        )

        async def get_default(user_id, exchange):
            await asyncio.sleep(0)
            return credential

        monkeypatch.setattr("trader.task.task_manager.BinanceExchange", FakeBinanceExchange)
        cfg = Config(tasks="[]", secret_key=service_key)
        log = _CaptureLog()
        manager = TaskManager(
            cfg,
            log,
            SimpleNamespace(exchange_credential=SimpleNamespace(get_default=get_default)),
            _FakeExchange(ExchangeConfig(api_key="base-key", api_secret="base-secret")),
        )

        routed = await manager._exchange_for_task(_live_task(chainer_mode="BOTH"))

        assert routed.cfg.margin_mode == MarginMode.CROSS_MARGIN
        assert any(
            "TaskManager selected execution exchange" in message
            and "target_margin_mode=cross_margin" in message
            and "actual_margin_mode=cross_margin" in message
            and "chainer_mode=BOTH" in message
            and "requires_short_capability=True" in message
            for message in log.messages
        )

    asyncio.run(run())


def test_user_live_exchange_routing_requires_service_secret():
    async def run():
        cfg = Config(tasks="[]")
        base_exchange = _FakeExchange(ExchangeConfig(api_key="base-key", api_secret="base-secret"))
        manager = TaskManager(
            cfg,
            Logger(cfg),
            SimpleNamespace(exchange_credential=SimpleNamespace(get_default=lambda *_args: None)),
            base_exchange,
        )

        with pytest.raises(RuntimeError, match="TRADER_SECRET_KEY"):
            await manager._ensure_routed_exchanges([_live_task()])

    asyncio.run(run())


def test_user_live_exchange_routing_requires_user_credential():
    async def run():
        async def get_default(_user_id, _exchange):
            return None

        cfg = Config(tasks="[]", secret_key="dev-service-secret")
        base_exchange = _FakeExchange(ExchangeConfig(api_key="base-key", api_secret="base-secret"))
        manager = TaskManager(
            cfg,
            Logger(cfg),
            SimpleNamespace(exchange_credential=SimpleNamespace(get_default=get_default)),
            base_exchange,
        )

        with pytest.raises(RuntimeError, match="missing BINANCE API credential"):
            await manager._ensure_routed_exchanges([_live_task()])

    asyncio.run(run())


def test_user_owned_real_auto_task_builds_task_with_user_exchange(monkeypatch):
    async def run():
        created_configs = []
        built_task_exchange_configs = []

        class FakeBinanceExchange(_FakeExchange):
            def __init__(self, cfg: ExchangeConfig, _log):
                super().__init__(cfg)
                self.quote_balance = 100.0
                created_configs.append(cfg)

            def get_account_balance(self, asset):
                return self.quote_balance if asset == "USDT" else 0.0

            def get_max_borrowable(self, asset, symbol=None):
                return {"amount": 0.0, "asset": asset, "symbol": symbol}

        class FakeTask:
            def __init__(self, cfg, exchange):
                self._id = cfg.id
                self.ts = TaskState(cfg.id, "fake-task", datetime.now())
                self.exchange = exchange

            def id(self):
                return self._id

            async def start(self, _queue):
                return None

            def stop(self):
                pass

        service_key = "dev-service-secret"
        credential = SimpleNamespace(
            id=12,
            encrypted_api_key=encrypt_secret(service_key, "user-api-key"),
            encrypted_api_secret=encrypt_secret(service_key, "user-api-secret"),
        )

        async def get_default(user_id, exchange):
            await asyncio.sleep(0)
            assert user_id == 7
            assert exchange == "BINANCE"
            return credential

        monkeypatch.setattr("trader.task.task_manager.BinanceExchange", FakeBinanceExchange)
        cfg = Config(tasks="[]", secret_key=service_key, cash=1000.0)
        base_exchange = _FakeExchange(ExchangeConfig(api_key="system-key", api_secret="system-secret"))
        base_exchange.get_account_balance = lambda asset: 999.0
        manager = TaskManager(
            cfg,
            Logger(cfg),
            SimpleNamespace(exchange_credential=SimpleNamespace(get_default=get_default)),
            base_exchange,
        )

        def build_task(task_cfg, exchange):
            built_task_exchange_configs.append(exchange.cfg)
            return FakeTask(task_cfg, exchange)

        manager._build_task = build_task
        task = _live_task(user_id=7)
        task.live_execution_mode = "auto_trade"
        task.free = 20.0

        await manager.do_add_tasks([task], asyncio.Queue())

        assert created_configs
        assert all(created.api_key == "user-api-key" for created in created_configs)
        assert all(created.api_secret == "user-api-secret" for created in created_configs)
        assert built_task_exchange_configs
        assert built_task_exchange_configs[0].api_key == "user-api-key"
        assert built_task_exchange_configs[0].api_secret == "user-api-secret"

    asyncio.run(run())


def test_user_exchange_routing_logs_credential_source(monkeypatch):
    async def run():
        class FakeBinanceExchange(_FakeExchange):
            def __init__(self, cfg: ExchangeConfig, _log):
                super().__init__(cfg)

        service_key = "dev-service-secret"
        credential = SimpleNamespace(
            id=12,
            encrypted_api_key=encrypt_secret(service_key, "user-api-key"),
            encrypted_api_secret=encrypt_secret(service_key, "user-api-secret"),
            masked_api_key="user***ikey",
        )

        async def get_default(_user_id, _exchange):
            await asyncio.sleep(0)
            return credential

        monkeypatch.setattr("trader.task.task_manager.BinanceExchange", FakeBinanceExchange)
        cfg = Config(tasks="[]", secret_key=service_key)
        log = _CaptureLog()
        manager = TaskManager(
            cfg,
            log,
            SimpleNamespace(exchange_credential=SimpleNamespace(get_default=get_default)),
            _FakeExchange(ExchangeConfig(api_key="system-key", api_secret="system-secret")),
        )

        routed = await manager._exchange_for_task(_live_task(user_id=7, chainer_mode="BOTH"))

        assert routed.cfg.api_key == "user-api-key"
        assert any(
            "TaskManager selected execution exchange" in message
            and "user_id=7" in message
            and "credential_id=12" in message
            and "api_key=user***ikey" in message
            for message in log.messages
        )

    asyncio.run(run())


def test_user_exchange_routing_refreshes_when_user_credential_changes(monkeypatch):
    async def run():
        class FakeBinanceExchange(_FakeExchange):
            def __init__(self, cfg: ExchangeConfig, _log):
                super().__init__(cfg)

        service_key = "dev-service-secret"
        credentials = [
            SimpleNamespace(
                id=12,
                encrypted_api_key=encrypt_secret(service_key, "first-user-api-key"),
                encrypted_api_secret=encrypt_secret(service_key, "first-user-api-secret"),
                masked_api_key="firs***-key",
            ),
            SimpleNamespace(
                id=12,
                encrypted_api_key=encrypt_secret(service_key, "second-user-api-key"),
                encrypted_api_secret=encrypt_secret(service_key, "second-user-api-secret"),
                masked_api_key="seco***-key",
            ),
        ]

        async def get_default(_user_id, _exchange):
            await asyncio.sleep(0)
            return credentials.pop(0)

        monkeypatch.setattr("trader.task.task_manager.BinanceExchange", FakeBinanceExchange)
        cfg = Config(tasks="[]", secret_key=service_key)
        manager = TaskManager(
            cfg,
            _CaptureLog(),
            SimpleNamespace(exchange_credential=SimpleNamespace(get_default=get_default)),
            _FakeExchange(ExchangeConfig(api_key="system-key", api_secret="system-secret")),
        )

        first = await manager._exchange_for_task(_live_task(user_id=7))
        second = await manager._exchange_for_task(_live_task(user_id=7))

        assert first.cfg.api_key == "first-user-api-key"
        assert second.cfg.api_key == "second-user-api-key"

    asyncio.run(run())
