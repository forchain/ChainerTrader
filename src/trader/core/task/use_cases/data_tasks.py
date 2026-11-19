"""Thin TaskRunner implementations for marketdata update, check, and CSV import tasks."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from trader.core.marketdata.interfaces import AvailabilityStore, DatasetFileStore, KlineRepository, MarketDataClient
from trader.core.marketdata.use_cases.check_klines import check_kline_continuity, check_kline_count
from trader.core.marketdata.use_cases.import_csv import import_csv_klines, parse_csv_kline_rows, validate_kline_interval
from trader.core.marketdata.use_cases.update_klines import (
    DEFAULT_OLDEST_TIME_TS,
    determine_update_time_range,
    download_range,
    sync_klines,
)
from trader.core.shared.async_utils import sleep
from trader.core.task.config import TaskConfig
from trader.core.task.domain import TaskState, TaskStateType, task_state_name
from trader.core.task.interfaces import TaskRepository


def _build_running_state(tcfg: TaskConfig, *, commission: float = 0.0, default_cash: float = 0.0) -> TaskState:
    ts = TaskState(
        tcfg.id,
        task_state_name(tcfg),
        datetime.now(),
        commission=commission,
        strategy_start_time=tcfg.start_time,
        strategy_end_time=tcfg.end_time,
        initial_cash=default_cash if tcfg.free < 0 else float(tcfg.free),
        user_id=getattr(tcfg, "user_id", None),
    )
    ts.state = TaskStateType.RUNNING
    return ts


async def _mark_done(ts: TaskState, task_repository: TaskRepository | None) -> TaskState:
    ts.state = TaskStateType.DONE
    if task_repository is not None:
        await task_repository.add_tasks([ts])
    return ts


class UpdateKlinesTaskRunner:
    """TaskRunner adapter for UPDATE_KLINES tasks."""

    def __init__(
        self,
        *,
        kline_repository: KlineRepository,
        market_data_client: MarketDataClient,
        availability_store: AvailabilityStore | None = None,
        task_repository: TaskRepository | None = None,
        log: Any = None,
        now_fn: Callable[[], int] | None = None,
        oldest_time_ts: int = DEFAULT_OLDEST_TIME_TS,
        range_downloader=download_range,
    ):
        self.kline_repository = kline_repository
        self.market_data_client = market_data_client
        self.availability_store = availability_store
        self.task_repository = task_repository
        self.log = log
        self.now_fn = now_fn
        self.oldest_time_ts = oldest_time_ts
        self.range_downloader = range_downloader

    async def run(self, cfg: TaskConfig, **kwargs: Any) -> TaskState:
        quit_event = kwargs.get("quit_event") or asyncio.Event()
        ts = kwargs.get("task_state") or _build_running_state(cfg)
        if self.task_repository is not None:
            await self.task_repository.add_tasks([ts])

        start_time, end_time = determine_update_time_range(
            cfg.symbol_interval,
            start_time=cfg.start_time,
            end_time=cfg.end_time,
            limit=cfg.limit,
            now_fn=self.now_fn,
            oldest_time_ts=self.oldest_time_ts,
        )
        await sync_klines(
            task_state_name(cfg),
            self.log,
            self.kline_repository,
            self.market_data_client,
            cfg.symbol_interval,
            start_time=start_time,
            end_time=end_time,
            force_update=bool(cfg.force_update),
            quit_event=quit_event,
            availability_store=self.availability_store,
            range_downloader=self.range_downloader,
        )
        return await _mark_done(ts, self.task_repository)


class CheckKlinesTaskRunner:
    """TaskRunner adapter for CHECK_KLINES continuity validation."""

    def __init__(
        self,
        *,
        kline_repository: KlineRepository,
        task_repository: TaskRepository | None = None,
        log: Any = None,
    ):
        self.kline_repository = kline_repository
        self.task_repository = task_repository
        self.log = log

    async def run(self, cfg: TaskConfig, **kwargs: Any) -> TaskState:
        quit_event = kwargs.get("quit_event") or asyncio.Event()
        ts = kwargs.get("task_state") or _build_running_state(cfg)
        if self.task_repository is not None:
            await self.task_repository.add_tasks([ts])

        name = task_state_name(cfg)
        self.log.info(f"Start {name}")
        count, total = await check_kline_continuity(
            self.kline_repository,
            cfg.symbol_interval,
            quit_event,
            self.log,
            name,
        )
        self.log.info(f"{name} process result:{count}/{total}")
        return await _mark_done(ts, self.task_repository)


class CheckKlinesNumTaskRunner:
    """TaskRunner adapter for CHECK_KLINES_NUM count validation."""

    def __init__(
        self,
        *,
        kline_repository: KlineRepository,
        task_repository: TaskRepository | None = None,
        log: Any = None,
    ):
        self.kline_repository = kline_repository
        self.task_repository = task_repository
        self.log = log

    async def run(self, cfg: TaskConfig, **kwargs: Any) -> TaskState:
        quit_event = kwargs.get("quit_event") or asyncio.Event()
        ts = kwargs.get("task_state") or _build_running_state(cfg)
        if self.task_repository is not None:
            await self.task_repository.add_tasks([ts])

        name = task_state_name(cfg)
        self.log.info(f"Start {name}")
        await check_kline_count(
            self.kline_repository,
            cfg.symbol_interval,
            cfg.limit,
            quit_event,
            self.log,
            name,
        )
        return await _mark_done(ts, self.task_repository)


class ImportCsvTaskRunner:
    """TaskRunner adapter for IMPORT_CSV tasks."""

    def __init__(
        self,
        *,
        kline_repository: KlineRepository,
        file_store: DatasetFileStore,
        data_dir: str | Path,
        task_repository: TaskRepository | None = None,
        log: Any = None,
    ):
        self.kline_repository = kline_repository
        self.file_store = file_store
        self.task_repository = task_repository
        self.data_dir = Path(data_dir)
        self.log = log

    def resolve_csv_path(self, csv_path: str) -> Path:
        raw = Path(csv_path)
        return raw if raw.is_absolute() else self.data_dir / raw

    async def run(self, cfg: TaskConfig, **kwargs: Any) -> TaskState:
        ts = kwargs.get("task_state") or _build_running_state(cfg)
        if self.task_repository is not None:
            await self.task_repository.add_tasks([ts])

        name = task_state_name(cfg)
        if not cfg.csv:
            self.log.error(f"No config data_file for {cfg.to_dict()}")
            return await _mark_done(ts, self.task_repository)

        data_file = self.resolve_csv_path(cfg.csv)
        kls = parse_csv_kline_rows(self.file_store.read_rows(data_file))
        if len(kls) <= 0:
            self.log.error(f"No kline in {data_file}")
            return await _mark_done(ts, self.task_repository)
        self.log.info(f"Read klines ({len(kls)}) from {data_file}")
        if not validate_kline_interval(kls, cfg.symbol_interval):
            self.log.error(f"{name} kline interval is not {cfg.symbol_interval.interval.name}")
            return await _mark_done(ts, self.task_repository)

        ret = await import_csv_klines(self.kline_repository, cfg.symbol_interval.name(), kls)
        if ret != len(kls):
            self.log.warning(f"{name} add klines to DB: {ret} != {len(kls)}")
        else:
            self.log.info(f"{name} add klines to DB: {ret}")
        return await _mark_done(ts, self.task_repository)


class DebugTaskRunner:
    """TaskRunner adapter for DEBUG countdown tasks."""

    def __init__(
        self,
        *,
        task_repository: TaskRepository | None = None,
        log: Any = None,
        sleep_fn: Callable[[Any, float], Any] = sleep,
    ):
        self.task_repository = task_repository
        self.log = log
        self.sleep_fn = sleep_fn

    async def run(self, cfg: TaskConfig, **kwargs: Any) -> TaskState:
        quit_event = kwargs.get("quit_event") or asyncio.Event()
        ts = kwargs.get("task_state") or _build_running_state(cfg)
        if self.task_repository is not None:
            await self.task_repository.add_tasks([ts])

        name = f"{cfg.id}.{cfg.ttype.name}"
        count = cfg.limit

        while count > 0:
            count -= 1

            if quit_event.is_set():
                self.log.info(f"Exit {name}. process={count}/{cfg.limit}")
                return ts

            self.log.info(f"Run {name}. process={count}/{cfg.limit}")

            await self.sleep_fn(self.log, 1)

        return await _mark_done(ts, self.task_repository)
