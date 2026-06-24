import asyncio
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
        assert len(created_configs) == 1

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
