"""Compatibility wrapper around ``LiveTraderTaskRunner`` for legacy ``TraderTask`` callers."""

from __future__ import annotations

from asyncio import Queue
from collections.abc import Callable
from typing import Any

from trader.adapters.outbound.backtrader.live_runtime import BacktraderLiveRunner
from trader.adapters.outbound.backtrader.live_trader_runner import LiveTraderTaskRunner
from trader.adapters.outbound.binance.exchange import BinanceExchange
from trader.adapters.outbound.execution_gateway_factory import build_execution_gateway
from trader.adapters.outbound.persistence.manager import DatabaseManager
from trader.common.config import Config
from trader.common.logger import Logger
from trader.core.execution.modes import normalize_live_execution_mode
from trader.core.task.interfaces import TaskEventPublisher
from trader.live.market_data import plan_initial_backfill
from trader.live.stream import GLOBAL_MARKET_STREAM_HUB
from trader.strategy.strategy import parse_strategies
from trader.strategy.trader_result import TraderResult
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig


class TraderTask(BaseTask):
    def __init__(
        self,
        tcfg: TaskConfig,
        cfg: Config,
        log: Logger,
        db_manager: DatabaseManager,
        exchange: BinanceExchange,
        event_publisher: TaskEventPublisher | None = None,
        execution_gateway_factory: Callable[[str, Any], Any] = build_execution_gateway,
    ):
        super().__init__(tcfg, cfg, log, db_manager, exchange)
        self.event_publisher = event_publisher
        self._execution_gateway_factory = execution_gateway_factory
        self._runner = self._make_runner()
        self._session = self._runner.build_session(tcfg, self.ts)
        self._manual_cash = self._session._manual_cash
        self._manual_position = self._session._manual_position
        self._auto_execution_router = self._session._auto_execution_router
        self.ts.auto_execution_outcomes = []
        self.ts.execution_reconcile = []

    def _make_runner(self) -> LiveTraderTaskRunner:
        return LiveTraderTaskRunner(
            cfg=self.cfg,
            log=self.log,
            exchange_client=self.exchange,
            execution_gateway=self._execution_gateway_factory(normalize_live_execution_mode(self.tcfg.live_execution_mode), self.exchange),
            execution_state_store=getattr(self.db_manager, "execution_state", None),
            task_repository=getattr(self.db_manager, "task", None),
            kline_repository=getattr(self.db_manager, "kline", None),
            fund_reservation_store=getattr(self.db_manager, "account_fund_reservation", None),
            market_stream=GLOBAL_MARKET_STREAM_HUB,
            event_publisher=self.event_publisher,
            live_runner_factory=BacktraderLiveRunner,
            strategy_parser=parse_strategies,
            backfill_planner=plan_initial_backfill,
        )

    def _sync_session(self) -> None:
        self._session.runner = self._make_runner()
        self._session._manual_cash = self._manual_cash
        self._session._manual_position = self._manual_position
        self._session._auto_execution_router = self._auto_execution_router

    def is_manual_notify_mode(self) -> bool:
        return self._session.is_manual_notify_mode()

    async def start(self, queue: Queue):
        if not self.tcfg.strategies:
            self.log.error(f"No config strategy for {self.tcfg.to_dict()}")
            return
        if not self.exchange:
            self.log.error(f"No config exchange for {self.tcfg.to_dict()}")
            return
        if not self.db_manager:
            self.log.error(f"No config db_uri for {self.tcfg.to_dict()}")
            return

        await super().start(queue)
        self._sync_session()
        await self._session.run(queue, self.quit)

    async def start_realtime(self, queue: Queue, strategy):
        self._sync_session()
        await self._session.run_realtime(queue, self.quit, strategy)

    async def _reconcile_execution_state(self) -> list[dict]:
        self._sync_session()
        return await self._session.reconcile_execution_state()

    async def _persist_auto_execution_state(self, outcome) -> None:
        self._sync_session()
        await self._session.persist_auto_execution_state(outcome)

    async def process_result(self, ret: TraderResult):
        self._sync_session()
        await self._session.process_result(ret)

    def handle_manual_trade_notifications(self, ret: TraderResult):
        self._sync_session()
        events = self._session.handle_manual_trade_notifications(ret)
        self._manual_cash = self._session._manual_cash
        self._manual_position = self._session._manual_position
        return events
