"""Backtest task runner adapter over backtrader and marketdata ports."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from trader.adapters.outbound.backtrader.catalog import parse_strategies
from trader.adapters.outbound.backtrader.csvdata import BinanceCSVData
from trader.adapters.outbound.backtrader.data import BinanceData
from trader.adapters.outbound.backtrader.node import Node
from trader.common import path
from trader.core.marketdata.interfaces import (
    AvailabilityStore,
    DatasetFileStore,
    KlineRepository,
    MarketDataClient,
)
from trader.core.marketdata.use_cases.dataset import DatasetResolver
from trader.core.shared.domain import get_time_duration
from trader.core.task.config import TaskConfig
from trader.core.task.domain import TaskState, TaskStateType, task_state_name
from trader.core.task.interfaces import TaskRepository


def backtest_data_start_time(cfg: Any, tcfg: TaskConfig) -> int:
    """Reserve the configured warmup candles before a bounded backtest."""
    if tcfg.start_time <= 0:
        return tcfg.start_time
    warmup_candles = max(0, int(getattr(cfg, "warmup_candles", 0) or 0))
    return max(0, tcfg.start_time - warmup_candles * get_time_duration(tcfg.symbol_interval.interval))


def build_csv_feed(data_file: str, *, data_start_time: int, start_time: int, end_time: int) -> BinanceCSVData:
    if start_time <= 0 and end_time <= 0:
        return BinanceCSVData(dataname=data_file)
    if start_time <= 0:
        return BinanceCSVData(dataname=data_file, todate=datetime.fromtimestamp(end_time))
    if end_time <= 0:
        return BinanceCSVData(dataname=data_file, fromdate=datetime.fromtimestamp(data_start_time))
    return BinanceCSVData(
        dataname=data_file,
        fromdate=datetime.fromtimestamp(data_start_time),
        todate=datetime.fromtimestamp(end_time),
    )


@dataclass(frozen=True)
class BacktestExecutionOutcome:
    task_state: TaskState
    trader_result: Any
    report: dict[str, Any] | None = None
    report_path: str | None = None


class BacktestTaskRunner:
    """TaskRunner adapter executing backtests through marketdata, backtrader, and task ports."""

    def __init__(
        self,
        *,
        cfg: Any,
        log: Any,
        task_repository: TaskRepository | None = None,
        kline_repository: KlineRepository | None = None,
        availability_store: AvailabilityStore | None = None,
        market_data_client: MarketDataClient | None = None,
        dataset_file_store: DatasetFileStore,
        dataset_resolver: Any = None,
        path_resolver: Callable[[str], str] = path.get_file_path,
        strategy_parser: Callable[[list[str]], Any] = parse_strategies,
        node_factory: Callable[..., Any] = Node,
    ):
        self.cfg = cfg
        self.log = log
        self.task_repository = task_repository
        self.kline_repository = kline_repository
        self.availability_store = availability_store
        self.market_data_client = market_data_client
        self.dataset_file_store = dataset_file_store
        self.dataset_resolver = dataset_resolver
        self.path_resolver = path_resolver
        self.strategy_parser = strategy_parser
        self.node_factory = node_factory

    def _get_dataset_resolver(self) -> DatasetResolver:
        if self.dataset_resolver is not None:
            return self.dataset_resolver
        return DatasetResolver(
            kline_repository=self.kline_repository,
            availability_store=self.availability_store,
            market_data_client=self.market_data_client,
            file_store=self.dataset_file_store,
            log=self.log,
        )

    async def prepare_inputs(self, tcfg: TaskConfig) -> tuple[Any, Any] | None:
        if not tcfg.csv and self.kline_repository is None:
            self.log.error(f"No config data_file or db for {tcfg.to_dict()}")
            return None
        if not tcfg.strategies:
            self.log.error(f"No config strategy for {tcfg.to_dict()}")
            return None

        data = None
        data_start_time = backtest_data_start_time(self.cfg, tcfg)
        if tcfg.csv:
            data_file = self.path_resolver(tcfg.csv)
            data = build_csv_feed(
                data_file,
                data_start_time=data_start_time,
                start_time=tcfg.start_time,
                end_time=tcfg.end_time,
            )

        dataset_path = tcfg.dataset_ref.path if tcfg.dataset_ref is not None else None
        if data is None and dataset_path:
            data = BinanceCSVData(dataname=dataset_path)

        if data is None and self.kline_repository is not None:
            resolver = self._get_dataset_resolver()
            allow_download = bool(tcfg.auto_download or tcfg.optimization_run_id is not None)
            prepare_result = await resolver.prepare(
                tcfg.symbol_interval,
                data_start_time,
                tcfg.end_time,
                allow_download=allow_download,
            )
            if not prepare_result.ok or prepare_result.dataset_ref is None:
                failure_msg = prepare_result.failure.message if prepare_result.failure else "unknown dataset error"
                self.log.error(f"Dataset preparation failed for {task_state_name(tcfg)}: {failure_msg}")
                return None
            tcfg.dataset_ref = prepare_result.dataset_ref
            klines = (
                await self.kline_repository.get_klines(
                    tcfg.symbol_interval.name(),
                    tcfg.dataset_ref.start_time,
                    tcfg.dataset_ref.end_time,
                )
                or []
            )
            if not klines:
                self.log.error(f"No kline data for {task_state_name(tcfg)} dataset={tcfg.dataset_ref.dataset_key}")
                return None
            data = BinanceData(klines)

        if data is None:
            self.log.error(f"No strategy data for {task_state_name(tcfg)}")
            return None

        strategy = self.strategy_parser(tcfg.strategies)
        if strategy is None:
            self.log.error(f"Not support strategy:{tcfg.strategy_name()}")
            return None
        return strategy, data

    async def run(self, tcfg: TaskConfig, **kwargs: Any) -> BacktestExecutionOutcome:
        ts = kwargs.get("task_state")
        if ts is None:
            ts = TaskState(
                tcfg.id,
                task_state_name(tcfg),
                datetime.now(),
                commission=float(getattr(self.cfg, "commission", 0.0) or 0.0),
                strategy_start_time=tcfg.start_time,
                strategy_end_time=tcfg.end_time,
                initial_cash=float(getattr(self.cfg, "cash", 0.0) or 0.0) if tcfg.free < 0 else float(tcfg.free),
                user_id=tcfg.user_id,
            )
        ts.state = TaskStateType.RUNNING
        if self.task_repository is not None:
            await self.task_repository.add_tasks([ts])

        prepared = await self.prepare_inputs(tcfg)
        if prepared is None:
            ts.state = TaskStateType.FAILED
            if self.task_repository is not None:
                await self.task_repository.add_tasks([ts])
            raise RuntimeError(f"failed to prepare backtest inputs for task {tcfg.id}")

        strategy, data = prepared
        free_cash = float(getattr(self.cfg, "cash", 0.0) or 0.0) if tcfg.free < 0 else float(tcfg.free)
        dataset_key = tcfg.dataset_ref.dataset_key if tcfg.dataset_ref is not None else None
        report_context = {
            "optimization_run_id": tcfg.optimization_run_id,
            "param_id": tcfg.param_id,
            "params": tcfg.strategy_params,
            "dataset_ref": dataset_key,
        }
        node = self.node_factory(
            tcfg.strategy_name(),
            strategy,
            tcfg.symbol_interval,
            self.cfg,
            self.log,
            data,
            position=0,
            trader=False,
            free=free_cash,
            strategy_params=tcfg.strategy_params,
            report_context=report_context,
        )
        run_inline = bool(kwargs.get("run_inline", False))
        ret = node.start() if run_inline else await asyncio.to_thread(node.start)
        ts.tret = ret
        ts.state = TaskStateType.DONE
        if self.task_repository is not None:
            await self.task_repository.add_tasks([ts])
        return BacktestExecutionOutcome(
            task_state=ts,
            trader_result=ret,
            report=getattr(node, "backtest_report", None),
            report_path=getattr(node, "backtest_report_path", None),
        )
