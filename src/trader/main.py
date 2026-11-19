"""Composition root: single place that parses edge config and wires concrete adapters into use cases."""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from trader.adapters.inbound.cli.env_config import new_and_env
from trader.adapters.inbound.cli.rendering import render_statistics_table
from trader.adapters.outbound.backtrader.backtest_runner import BacktestTaskRunner
from trader.adapters.outbound.backtrader.catalog import (
    BacktraderStrategyCatalog,
    list_strategy_options,
    strategy_param_defaults,
)
from trader.adapters.outbound.backtrader.live_trader_runner import LiveTraderTaskRunner
from trader.adapters.outbound.backtrader.optimization_runner import ProcessPoolBacktestRunner
from trader.adapters.outbound.backtrader.sample_worker import backtest_data_start_time, build_backtest_sample_spec, process_backtrader
from trader.adapters.outbound.backtrader.signal_scanner import BacktraderSignalScanRunner
from trader.adapters.outbound.backtrader.task_handles import BacktestTaskHandle, LiveTraderTaskHandle
from trader.adapters.outbound.binance.exchange import BinanceExchange, get_oldest_time
from trader.adapters.outbound.email.config import parse_notice_config
from trader.adapters.outbound.execution_gateway_factory import build_execution_gateway
from trader.adapters.outbound.files import paths as path
from trader.adapters.outbound.files.dataset import CsvDatasetFileStore
from trader.adapters.outbound.files.optimization_store import (
    FileOptimizationRuntimeStatus,
    FileRankingReportStore,
    FileTaskConfigFileStore,
)
from trader.adapters.outbound.files.task_config_loader import FileTaskConfigSourceLoader
from trader.adapters.outbound.identity.argon2_hasher import Argon2PasswordHasher
from trader.adapters.outbound.identity.fernet_cipher import FernetSecretCipher, service_key_available
from trader.adapters.outbound.logging.logger import Logger
from trader.adapters.outbound.persistence.manager import DatabaseManager, DatabaseSchemaError
from trader.core.exchange.domain import ExchangeType, MarginMode, parse_exchange_config
from trader.core.identity.exceptions import PasswordPolicyError
from trader.core.identity.use_cases import BootstrapAdministrator, bootstrap_admin_exchange_credential
from trader.core.notification.manager import NotifyManager
from trader.core.shared.config import Config, default
from trader.core.shared.logging import LogTag
from trader.core.task.event_bus import LiveEventBus
from trader.core.task.interfaces import TaskEventPublisher
from trader.core.task.runtime_task import RunnerTaskHandle
from trader.core.task.use_cases import PlanStartupTasks, RecoverRunningTasks
from trader.core.task.use_cases.data_tasks import (
    CheckKlinesNumTaskRunner,
    CheckKlinesTaskRunner,
    DebugTaskRunner,
    ImportCsvTaskRunner,
    UpdateKlinesTaskRunner,
)
from trader.core.task.use_cases.statistics import Statistics
from trader.task.live_startup_self_check import infer_required_margin_mode
from trader.task.persisted_live_config_migration import assert_persisted_task_config_json_is_migrated
from trader.task.task_config import TaskConfig, parse_task_config
from trader.task.task_manager import TaskManager
from trader.task.task_type import TaskType


def version() -> str:
    file_path = os.path.join(path.GetTraderDir(), "VERSION")
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


@dataclass
class AppContainer:
    cfg: Config
    logger: Logger
    live_event_bus: TaskEventPublisher
    db_manager: DatabaseManager | None
    exchange: BinanceExchange | None
    tasks_cfg: list[TaskConfig]
    notify_mgr: NotifyManager
    stat: Statistics
    password_hasher: Argon2PasswordHasher
    report_store: FileRankingReportStore
    config_file_store: FileTaskConfigFileStore
    task_manager: TaskManager
    bootstrap_admin_fn: Callable[[], Any]
    startup_planner: PlanStartupTasks
    recovery_runner: RecoverRunningTasks
    version: Callable[[], str] = version
    user_exchange_factory: Any = BinanceExchange
    secret_cipher_factory: Callable[[str | None], Any] | None = None
    secret_key_ready_fn: Callable[[], bool] | None = None
    schema_error_cls: type[Exception] = DatabaseSchemaError
    backtest_runner_cls: type[BacktestTaskRunner] = BacktestTaskRunner
    live_trader_runner_cls: type[LiveTraderTaskRunner] = LiveTraderTaskRunner
    strategy_options: Callable[[], list[str]] = list_strategy_options
    strategy_param_defaults: Callable[[str], dict] = strategy_param_defaults
    strategy_loader: Any = None
    task_config_loader: Any = None


class _MainTaskRunnerFactory:
    """Composition-root factory mapping task types to concrete managed task handles."""

    def __init__(self, cfg: Config, log: Any, db_manager: Any, event_publisher: TaskEventPublisher | None, execution_gateway_factory):
        self.cfg = cfg
        self.log = log
        self.db_manager = db_manager
        self.event_publisher = event_publisher
        self._execution_gateway_factory = execution_gateway_factory

    def build(self, cfg: TaskConfig, exchange: Any):
        task_repository = getattr(self.db_manager, "task", None)
        if cfg.ttype == TaskType.TRADER:
            return LiveTraderTaskHandle(
                cfg,
                self.cfg,
                self.log,
                self.db_manager,
                exchange,
                event_publisher=self.event_publisher,
                execution_gateway_factory=self._execution_gateway_factory,
            )
        if cfg.ttype == TaskType.BACK_TRADER:
            return BacktestTaskHandle(cfg, self.cfg, self.log, self.db_manager, exchange)

        def runner_handle(runner, *, include_symbol_in_name: bool = True):
            return RunnerTaskHandle(
                runner=runner,
                tcfg=cfg,
                cfg=self.cfg,
                log=self.log,
                task_repository=task_repository,
                exchange=exchange,
                include_symbol_in_name=include_symbol_in_name,
            )

        if cfg.ttype == TaskType.UPDATE_KLINES:
            if not exchange or not self.db_manager:
                self.log.error(f"Missing exchange or db for {cfg.to_dict()}")
                return None
            return runner_handle(
                UpdateKlinesTaskRunner(
                    kline_repository=self.db_manager.kline,
                    market_data_client=exchange,
                    availability_store=getattr(self.db_manager, "availability", None),
                    task_repository=task_repository,
                    log=self.log,
                    oldest_time_ts=int(get_oldest_time().timestamp()),
                )
            )
        if cfg.ttype == TaskType.CHECK_KLINES:
            if not self.db_manager:
                self.log.error(f"No config db_uri for {cfg.to_dict()}")
                return None
            return runner_handle(CheckKlinesTaskRunner(kline_repository=self.db_manager.kline, task_repository=task_repository, log=self.log))
        if cfg.ttype == TaskType.CHECK_KLINES_NUM:
            if not self.db_manager:
                self.log.error(f"No config db_uri for {cfg.to_dict()}")
                return None
            return runner_handle(
                CheckKlinesNumTaskRunner(kline_repository=self.db_manager.kline, task_repository=task_repository, log=self.log)
            )
        if cfg.ttype == TaskType.IMPORT_CSV:
            if not cfg.csv or not self.db_manager:
                self.log.error(f"Missing data_file or db_uri for {cfg.to_dict()}")
                return None
            return runner_handle(
                ImportCsvTaskRunner(
                    kline_repository=self.db_manager.kline,
                    file_store=CsvDatasetFileStore(),
                    task_repository=task_repository,
                    data_dir=path.GetDataDir(),
                    log=self.log,
                )
            )
        if cfg.ttype == TaskType.DEBUG:
            return runner_handle(DebugTaskRunner(task_repository=task_repository, log=self.log), include_symbol_in_name=False)
        return None

    def build_sample_spec(self, cfg: TaskConfig):
        return build_backtest_sample_spec(self.cfg, cfg)

    async def run_backtest_task(self, task: Any, queue: Any) -> list[Any]:
        task_params = await task.start(queue)
        if task_params is None:
            return []
        result: list[Any] = []
        await asyncio.to_thread(
            process_backtrader,
            [self.cfg, task_params[1], task_params[0], task.tcfg, task.ts],
            result,
        )
        for msg, logs, _report_record in result:
            for log_str in logs:
                self.log.add_log_buffer(log_str, LogTag.STRATEGY)
            self.log.info(f"Relay process queue message:{msg.name()}", LogTag.STRATEGY)
            await queue.put(msg)
        return result


def compose_application(
    cfg: Config = default(),
    *,
    event_publisher: TaskEventPublisher | None = None,
    tasks_cfg: list[TaskConfig] | None = None,
    task_parser: Callable[[str], list[TaskConfig]] | None = None,
    logger: Logger | None = None,
) -> AppContainer:
    """Wire all concrete outbound adapters, use cases, and task orchestrators."""
    app_logger = logger or Logger(cfg)
    event_bus = event_publisher or LiveEventBus()
    parser = task_parser or parse_task_config

    db_manager = DatabaseManager(cfg, app_logger) if cfg.db else None
    parsed_tasks: list[TaskConfig] = list(tasks_cfg) if tasks_cfg is not None else (parser(cfg.tasks) if cfg.tasks else [])

    exchange = None
    if cfg.exchange:
        ex_cfg = parse_exchange_config(cfg.exchange)
        if ex_cfg and ex_cfg.ty == ExchangeType.BINANCE:
            required_margin_mode = infer_required_margin_mode(parsed_tasks)
            if required_margin_mode == MarginMode.CROSS_MARGIN and ex_cfg.margin_mode == MarginMode.SPOT:
                ex_cfg = ex_cfg.with_margin_mode(MarginMode.CROSS_MARGIN)
            exchange = BinanceExchange(ex_cfg, app_logger.log())

    notify_mgr = NotifyManager(cfg, app_logger, notices=parse_notice_config(cfg.notice) if cfg.notice else None)
    stat = Statistics(cfg, app_logger.log(), db_manager, table_renderer=render_statistics_table)
    password_hasher = Argon2PasswordHasher()
    report_store = FileRankingReportStore(Path.cwd())
    config_file_store = FileTaskConfigFileStore()

    def build_optimization_runner(
        *,
        prepare_dataset_job_fn,
        sample_max_workers,
        dataset_prepare_max_workers,
        dataset_prepare_timeout_seconds,
        dataset_download_request_budget,
        sample_timeout_seconds,
    ):
        return ProcessPoolBacktestRunner(
            cfg=cfg,
            db_manager=db_manager,
            exchange=exchange,
            log=app_logger,
            prepare_dataset_job_fn=prepare_dataset_job_fn,
            sample_max_workers=sample_max_workers,
            dataset_prepare_max_workers=dataset_prepare_max_workers,
            dataset_prepare_timeout_seconds=dataset_prepare_timeout_seconds,
            dataset_download_request_budget=dataset_download_request_budget,
            sample_timeout_seconds=sample_timeout_seconds,
            process_pool_factory=ProcessPoolExecutor,
        )

    def build_runtime_status(run_id: str, run_cfgs: list[TaskConfig], max_workers: int):
        return FileOptimizationRuntimeStatus(
            Path.cwd() / "tmp" / "optimization_runs" / run_id,
            run_id,
            total_samples=len(run_cfgs),
            total_datasets=len(
                {
                    (item.symbol_interval.name(), backtest_data_start_time(cfg, item), item.end_time)
                    for item in run_cfgs
                    if item.ttype == TaskType.BACK_TRADER and not item.csv
                }
            ),
            configured_workers=max_workers,
        )

    def exchange_factory(ex_cfg, log=None):
        return BinanceExchange(ex_cfg, log or app_logger.log())
    task_runner_factory = _MainTaskRunnerFactory(cfg, app_logger, db_manager, event_bus, build_execution_gateway)
    task_manager = TaskManager(
        cfg,
        app_logger,
        db_manager,
        exchange,
        event_publisher=event_bus,
        task_runner_factory=task_runner_factory,
        task_config_loader=FileTaskConfigSourceLoader(),
        exchange_factory=exchange_factory,
        report_store=report_store,
        optimization_runner_factory=build_optimization_runner,
        runtime_status_factory=build_runtime_status,
        cipher_factory=lambda service_key: FernetSecretCipher(service_key) if service_key_available(service_key) else None,
        execution_gateway_factory=build_execution_gateway,
    )

    async def bootstrap_identity() -> None:
        if not db_manager or not getattr(db_manager, "user", None):
            return
        try:
            admin = await BootstrapAdministrator(db_manager.user, password_hasher).execute(
                cfg.auth_username,
                cfg.auth_password,
            )
        except PasswordPolicyError as exc:
            raise DatabaseSchemaError(f"invalid bootstrap administrator credentials: {exc}") from exc
        if admin is not None:
            await bootstrap_admin_exchange_credential(
                cfg=cfg,
                admin=admin,
                credential_repo=db_manager.exchange_credential,
                log=app_logger.log(),
                cipher_factory=lambda key: FernetSecretCipher(key) if service_key_available(key) else None,
            )

    startup_planner = PlanStartupTasks(
        getattr(db_manager, "task", None),
        config_parser=parser,
        migration_validator=assert_persisted_task_config_json_is_migrated,
        log=app_logger,
    )
    recovery_runner = RecoverRunningTasks(max_concurrency=10)

    return AppContainer(
        cfg=cfg,
        logger=app_logger,
        live_event_bus=event_bus,
        db_manager=db_manager,
        exchange=exchange,
        tasks_cfg=parsed_tasks,
        notify_mgr=notify_mgr,
        stat=stat,
        password_hasher=password_hasher,
        report_store=report_store,
        config_file_store=config_file_store,
        task_manager=task_manager,
        bootstrap_admin_fn=bootstrap_identity,
        startup_planner=startup_planner,
        recovery_runner=recovery_runner,
        secret_cipher_factory=lambda key: FernetSecretCipher(key) if service_key_available(key) else None,
        secret_key_ready_fn=lambda: service_key_available(getattr(cfg, "secret_key", None)),
        strategy_options=list_strategy_options,
        strategy_param_defaults=strategy_param_defaults,
        strategy_loader=BacktraderStrategyCatalog(),
        task_config_loader=FileTaskConfigSourceLoader(),
    )


def compose_signal_scanner() -> tuple[Config, Logger, DatabaseManager, BinanceExchange, BacktraderSignalScanRunner]:
    """Compose the top-volume signal scanner runtime (exchange, database, and Backtrader runner)."""
    cfg = new_and_env()
    if not cfg.exchange:
        raise ValueError("TRADER_EXCHANGE is required")
    if not cfg.db:
        raise ValueError("TRADER_DB is required")
    logger = Logger(cfg)
    db_manager = DatabaseManager(cfg, logger)
    db_manager.start()
    ex_cfg = parse_exchange_config(cfg.exchange)
    exchange = BinanceExchange(ex_cfg, logger.log())
    return cfg, logger, db_manager, exchange, BacktraderSignalScanRunner()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Implement TradingView Algorithms of Youtube Channel Shi Hun",
        epilog="Chainer Labs",
        fromfile_prefix_chars="@",
    )

    parser.add_argument("-v", "--version", help="Version", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument(
        "--period",
        help="Period for the moving average",
        action="store",
        type=int,
        default=argparse.SUPPRESS,
        required=False,
    )
    parser.add_argument(
        "--commission",
        help="Transaction commission",
        action="store",
        type=float,
        default=argparse.SUPPRESS,
        required=False,
    )
    parser.add_argument(
        "--api",
        help="Start the Web API service with optional binding address and port (e.g. 127.0.0.1:8000, :8000, 127.0.0.1)",
        nargs="?",
        type=str,
        const="127.0.0.1:8000",
        default=argparse.SUPPRESS,
    )
    parser.add_argument("--log_file", help="Write log to file (optional path)", nargs="?", const=True, type=str, default=argparse.SUPPRESS)
    parser.add_argument("--plot", help="Plot data", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument("--mode", help="trend type: NORMAL UP DOWN", type=str, default=argparse.SUPPRESS)
    parser.add_argument(
        "--log_level",
        help="logger display level:CRITICAL,FATAL,ERROR,WARNING,WARNING,INFO,DEBUG",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--exchange",
        help="Which remote exchange is connected to.support json:BINANCE or {name:BINANCE,api_key:'',api_secret:''}",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--db",
        help="Enable database with a Tortoise ORM URL (default: sqlite://data/trader.db)",
        nargs="?",
        const="sqlite://data/trader.db",
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--db_name",
        help="Deprecated legacy MongoDB database name; ignored by SQL database URLs",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--window",
        help="Window for backtesting",
        action="store",
        type=int,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--warmup-candles",
        help="Max realtime warmup candles loaded at startup (default: 500)",
        action="store",
        type=int,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--live-order-cleanup-symbols",
        help="Comma-separated symbols to clean before live task start/stop, e.g. BTC-USDT,ETHUSDT",
        action="store",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--tasks",
        help="Tasks config:TRADER,BACK_TRADER,UPDATE_KLINES,CHECK_KLINES,IMPORT_CSV",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--cash",
        help="Init cash for backtesting",
        action="store",
        type=float,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--stat",
        help="The maximum number of entries displayed in statistics for backtesting",
        action="store",
        type=int,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--notice",
        help="Load notification configuration files, such as email",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--auth-username",
        help="Bootstrap administrator username for the web login system (optional)",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--auth-password",
        help="Bootstrap administrator password for the web login system (optional)",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--protected-paths",
        help="Deprecated legacy Basic Auth option; session auth protects the web console when bootstrap credentials are configured",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--secret-key",
        help="Service-level key used to encrypt per-user exchange API credentials",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--session-cookie-secure",
        help="Mark session cookies as Secure; enable behind HTTPS",
        action="store_true",
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--session-ttl-hours",
        help="Web login session lifetime in hours",
        type=int,
        default=argparse.SUPPRESS,
    )
    registration_group = parser.add_mutually_exclusive_group()
    registration_group.add_argument(
        "--registration-enabled",
        dest="registration_enabled",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Enable public user registration",
    )
    registration_group.add_argument(
        "--no-registration",
        dest="registration_enabled",
        action="store_false",
        default=argparse.SUPPRESS,
        help="Disable public user registration",
    )
    return parser


def _parse_bind_addr(bind_addr: str | None) -> tuple[str, int]:
    addr = bind_addr or "127.0.0.1:8000"
    if ":" in addr:
        host, port_text = addr.rsplit(":", 1)
        return (host or "127.0.0.1"), int(port_text)
    return addr, 8000


def run_api_mode(cfg: Config) -> None:
    from contextlib import asynccontextmanager

    import uvicorn

    from trader.adapters.inbound.http import create_app
    from trader.adapters.inbound.http.lifecycle import ApiServerLifecycle

    container = compose_application(cfg)

    @asynccontextmanager
    async def api_lifespan(fast_app):
        rpc_app = ApiServerLifecycle(container=container)
        fast_app.state.app = rpc_app
        fast_app.state.live_event_bus = getattr(rpc_app, "live_event_bus", None) or container.live_event_bus
        await rpc_app.bootstrap_database_for_startup()
        await rpc_app.start_async()
        await rpc_app.wait_until_handler_ready()
        rpc_app.raise_main_task_error()
        yield
        await rpc_app.stop()

    host, port = _parse_bind_addr(cfg.api)
    web_app = create_app(container, lifespan=api_lifespan)
    uvicorn.run(
        web_app,
        host=host,
        port=port,
        reload=False,
        app_dir=os.path.join(path.GetTraderDir(), "rpc"),
        log_level=cfg.get_log_level(),
    )


def run_console_mode(cfg: Config) -> None:
    from trader.adapters.inbound.cli import run_console

    run_console(compose_application(cfg))


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    load_dotenv()

    cfg = new_and_env(args)
    if getattr(args, "version", False):
        print(version())
        return

    if cfg.api:
        run_api_mode(cfg)
    else:
        run_console_mode(cfg)
