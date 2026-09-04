import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from trader.common import path
from trader.common.config import Config
from trader.common.log_tag import LogTag
from trader.common.logger import Logger
from trader.common.message import new_stat_msg
from trader.database.manager import DatabaseManager
from trader.exchange.binance.csvdata import BinanceCSVData
from trader.exchange.binance.data import BinanceData
from trader.exchange.binance.exchange import BinanceExchange
from trader.statistics.stat import BackTraderStat
from trader.strategy.trader_result import TraderResult, parse_trader_result
from trader.strategy.node import Node
from trader.strategy.strategy import parse_strategies
from trader.task.base_task import BaseTask
from trader.task.dataset_resolver import DatasetResolver
from trader.task.task_config import TaskConfig
from trader.task.update_klines_task import download_range
from trader.utils.symbol_interval import Interval, SymbolInterval


@dataclass(frozen=True)
class BacktestSampleSpec:
    task_id: int
    strategy_name: str
    strategy_names: list[str]
    symbol: str
    interval: str
    start_time: int
    end_time: int
    cfg: dict[str, Any]
    strategy_params: dict[str, Any]
    optimization_run_id: str | None
    param_id: str | None
    dataset_key: str | None
    source_type: str = "csv"
    data_path: str | None = None
    db_url: str | None = None
    use_data_range: bool = False
    free_cash: float = 0.0


@dataclass(frozen=True)
class BacktestSampleResult:
    ok: bool
    task_id: int
    trader_result: dict[str, Any] | None
    logs: list[str]
    report: dict[str, Any] | None
    report_path: str | None
    error: str | None = None
    timed_out: bool = False


def build_backtest_sample_spec(cfg: Config, tcfg: TaskConfig) -> BacktestSampleSpec:
    data_path = None
    use_data_range = False
    dataset_key = getattr(tcfg.dataset_ref, "dataset_key", None) if tcfg.dataset_ref else None
    source_type = "db"

    if tcfg.csv:
        source_type = "csv"
        data_path = path.get_file_path(tcfg.csv)
        use_data_range = tcfg.start_time > 0 or tcfg.end_time > 0
    elif tcfg.dataset_ref is not None:
        source_type = getattr(tcfg.dataset_ref, "source_type", None)
        data_path = getattr(tcfg.dataset_ref, "path", None)
        if source_type is None:
            source_type = "csv" if data_path else "db"

    if source_type == "csv" and data_path is None:
        raise ValueError(f"missing data source for backtest sample task_id={tcfg.id}")
    if source_type == "db" and not cfg.db:
        raise ValueError(f"missing database URL for backtest sample task_id={tcfg.id}")

    free_cash = cfg.cash if tcfg.free < 0 else tcfg.free
    symbol = f"{tcfg.symbol_interval.sy.base}-{tcfg.symbol_interval.sy.quote}"
    return BacktestSampleSpec(
        task_id=tcfg.id,
        strategy_name=tcfg.strategy_name(),
        strategy_names=list(tcfg.strategies or []),
        symbol=symbol,
        interval=tcfg.symbol_interval.interval.value,
        start_time=tcfg.start_time,
        end_time=tcfg.end_time,
        source_type=source_type,
        data_path=data_path,
        db_url=cfg.db,
        use_data_range=use_data_range,
        free_cash=free_cash,
        cfg=cfg.to_dict(),
        strategy_params=dict(tcfg.strategy_params),
        optimization_run_id=tcfg.optimization_run_id,
        param_id=tcfg.param_id,
        dataset_key=dataset_key,
    )


def _build_csv_data_for_spec(spec: BacktestSampleSpec):
    if spec.data_path is None:
        raise ValueError(f"missing CSV path for backtest sample task_id={spec.task_id}")
    if not spec.use_data_range:
        return BinanceCSVData(dataname=spec.data_path)
    if spec.start_time <= 0 and spec.end_time <= 0:
        return BinanceCSVData(dataname=spec.data_path)
    if spec.start_time <= 0:
        return BinanceCSVData(
            dataname=spec.data_path,
            todate=datetime.fromtimestamp(spec.end_time),
        )
    if spec.end_time <= 0:
        return BinanceCSVData(
            dataname=spec.data_path,
            fromdate=datetime.fromtimestamp(spec.start_time),
        )
    return BinanceCSVData(
        dataname=spec.data_path,
        fromdate=datetime.fromtimestamp(spec.start_time),
        todate=datetime.fromtimestamp(spec.end_time),
    )


async def _build_db_data_for_spec(spec: BacktestSampleSpec, cfg: Config, logger: Logger):
    db_manager = DatabaseManager(cfg, logger)
    await db_manager.start()
    try:
        symbol_interval = SymbolInterval(spec.symbol, Interval(spec.interval))
        klines = await db_manager.kline.get_klines(symbol_interval.name(), spec.start_time, spec.end_time) or []
        if not klines:
            raise ValueError(f"no kline data available for dataset={spec.dataset_key}")
        return BinanceData(klines)
    finally:
        await db_manager.stop()


def _build_data_for_spec(spec: BacktestSampleSpec, cfg: Config, logger: Logger):
    if spec.source_type == "csv":
        return _build_csv_data_for_spec(spec)
    if spec.source_type == "db":
        return asyncio.run(_build_db_data_for_spec(spec, cfg, logger))
    raise ValueError(f"unsupported backtest sample source_type={spec.source_type}")


def _write_worker_pid(run_id: str | None, task_id: int) -> Path | None:
    """Write a <pid>.json mapping file so the dashboard knows which task this process is running."""
    if not run_id:
        return None
    pid = os.getpid()
    workers_dir = Path.cwd() / "tmp" / "optimization_runs" / run_id / "workers"
    workers_dir.mkdir(parents=True, exist_ok=True)
    pid_file = workers_dir / f"{pid}.json"
    payload = {
        "pid": pid,
        "task_id": task_id,
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    tmp = pid_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(pid_file)
    return pid_file


def run_backtest_sample(spec: BacktestSampleSpec) -> BacktestSampleResult:
    cfg = Config(**spec.cfg)
    if spec.db_url:
        cfg.db = spec.db_url
    logger = Logger(cfg, 10000, True)
    pid_file = _write_worker_pid(spec.optimization_run_id, spec.task_id)
    try:
        strategy = parse_strategies(spec.strategy_names)
        if strategy is None:
            return BacktestSampleResult(
                ok=False,
                task_id=spec.task_id,
                trader_result=None,
                logs=logger.get_buffer_str(),
                report=None,
                report_path=None,
                error=f"Not support strategy:{spec.strategy_name}",
            )

        data = _build_data_for_spec(spec, cfg, logger)
        symbol_interval = SymbolInterval(spec.symbol, Interval(spec.interval))
        report_context = {
            "optimization_run_id": spec.optimization_run_id,
            "param_id": spec.param_id,
            "params": spec.strategy_params,
            "dataset_ref": spec.dataset_key,
        }
        node = Node(
            spec.strategy_name,
            strategy,
            symbol_interval,
            cfg,
            logger,
            data,
            position=0,
            trader=False,
            free=spec.free_cash,
            strategy_params=spec.strategy_params,
            report_context=report_context,
        )
        ret: TraderResult | None = node.start()
        if ret is None:
            return BacktestSampleResult(
                ok=False,
                task_id=spec.task_id,
                trader_result=None,
                logs=logger.get_buffer_str(),
                report=node.backtest_report,
                report_path=node.backtest_report_path,
                error="backtest returned no result",
            )

        return BacktestSampleResult(
            ok=True,
            task_id=spec.task_id,
            trader_result=ret.to_dict(),
            logs=logger.get_buffer_str(),
            report=node.backtest_report,
            report_path=node.backtest_report_path,
        )
    except Exception as exc:
        logger.error(f"backtest sample failed: task_id={spec.task_id}, error={exc}")
        return BacktestSampleResult(
            ok=False,
            task_id=spec.task_id,
            trader_result=None,
            logs=logger.get_buffer_str(),
            report=None,
            report_path=None,
            error=str(exc),
        )
    finally:
        if pid_file and pid_file.exists():
            try:
                pid_file.unlink()
            except OSError:
                pass


class BackTraderTask(BaseTask):
    def __init__(
        self,
        tcfg: TaskConfig,
        cfg: Config,
        log: Logger,
        db_manager: DatabaseManager,
        exchange: BinanceExchange,
    ):
        super().__init__(tcfg, cfg, log, db_manager, exchange)

    async def start(self, queue):
        if not self.tcfg.csv and not self.db_manager:
            self.log.error(f"No config data_file or db for {self.tcfg.to_dict()}")
            return None
        if not self.tcfg.strategies:
            self.log.error(f"No config strategy for {self.tcfg.to_dict()}")
            return None

        await super().start(queue)

        data = None
        if self.tcfg.csv:
            data_file = path.get_file_path(self.tcfg.csv)
            if self.tcfg.start_time <= 0 and self.tcfg.end_time <= 0:
                data = BinanceCSVData(
                    dataname=data_file,
                )
            elif self.tcfg.start_time <= 0:
                data = BinanceCSVData(
                    dataname=data_file,
                    todate=datetime.fromtimestamp(self.tcfg.end_time),
                )
            elif self.tcfg.end_time <= 0:
                data = BinanceCSVData(
                    dataname=data_file,
                    fromdate=datetime.fromtimestamp(self.tcfg.start_time),
                )
            else:
                data = BinanceCSVData(
                    dataname=data_file,
                    fromdate=datetime.fromtimestamp(self.tcfg.start_time),
                    todate=datetime.fromtimestamp(self.tcfg.end_time),
                )
        if data is None and self.tcfg.dataset_ref is not None and getattr(self.tcfg.dataset_ref, "path", None):
            data = BinanceCSVData(dataname=self.tcfg.dataset_ref.path)
        if self.db_manager and data is None:
            resolver = DatasetResolver(self.db_manager, self.exchange, self.log)
            allow_download = self.tcfg.auto_download or self.tcfg.optimization_run_id is not None
            prepare_result = await resolver.prepare(
                self.tcfg.symbol_interval,
                self.tcfg.start_time,
                self.tcfg.end_time,
                allow_download=allow_download,
            )
            if not prepare_result.ok:
                self.log.error(f"Dataset preparation failed for {self.name()}: {prepare_result.failure.message}")
                return None
            self.tcfg.dataset_ref = prepare_result.dataset_ref
            klines = (
                await self.db_manager.kline.get_klines(
                    self.tcfg.symbol_interval.name(),
                    self.tcfg.dataset_ref.start_time,
                    self.tcfg.dataset_ref.end_time,
                )
                or []
            )
            if not klines:
                self.log.error(f"No kline data for {self.name()} dataset={self.tcfg.dataset_ref.dataset_key}")
                return None
            data = BinanceData(klines)

        if data is None:
            self.log.error(f"No strategy data for {self.name()}")
            return None
        strategy = parse_strategies(self.tcfg.strategies)
        if strategy is None:
            self.log.error(f"Not support strategy:{self.tcfg.strategy_name()}")
            return None
        return [strategy, data]


def process_backtrader(parmas, result):
    cfg = parmas[0]
    data = parmas[1]
    strategy = parmas[2]
    tcfg = parmas[3]
    ts = parmas[4]
    if (tcfg.dataset_ref is None or not getattr(tcfg.dataset_ref, "path", None)) and data is not None and strategy is not None:
        logger = Logger(cfg, 10000, True)
        free_cash = cfg.cash if tcfg.free < 0 else tcfg.free
        report_context = {
            "optimization_run_id": tcfg.optimization_run_id,
            "param_id": tcfg.param_id,
            "params": tcfg.strategy_params,
            "dataset_ref": getattr(tcfg.dataset_ref, "dataset_key", None) if tcfg.dataset_ref else None,
        }
        node = Node(
            tcfg.strategy_name(),
            strategy,
            tcfg.symbol_interval,
            cfg,
            logger,
            data,
            position=0,
            trader=False,
            free=free_cash,
            strategy_params=tcfg.strategy_params,
            report_context=report_context,
        )
        ret = node.start()
        if ret is None:
            return
        ts.tret = ret
        result.append(
            [
                new_stat_msg(
                    BackTraderStat(tcfg.strategy_name(), tcfg.symbol_interval.name(), ts),
                    tcfg.id,
                ),
                logger.log_buffer.get_logs(),
                {
                    "task_id": tcfg.id,
                    "report": node.backtest_report,
                    "report_path": node.backtest_report_path,
                },
            ]
        )
        return

    sample_spec = build_backtest_sample_spec(cfg, tcfg)
    sample_result = run_backtest_sample(sample_spec)
    if not sample_result.ok or sample_result.trader_result is None:
        return

    ts.tret = parse_trader_result(sample_result.trader_result)

    result.append(
        [
            new_stat_msg(
                BackTraderStat(tcfg.strategy_name(), tcfg.symbol_interval.name(), ts),
                tcfg.id,
            ),
            sample_result.logs,
            {
                "task_id": tcfg.id,
                "report": sample_result.report,
                "report_path": sample_result.report_path,
            },
        ]
    )
