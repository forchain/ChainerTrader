import asyncio
import inspect
import os
from asyncio import Queue
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime
from pathlib import Path

from trader.auth.credentials import service_key_available
from trader.common.common import sleep
from trader.common.config import Config
from trader.common.log_tag import LogTag
from trader.common.logger import Logger
from trader.common.message import new_add_tasks_msg, new_exit_msg, new_stat_msg
from trader.database.account_fund_reservation import FundReservationError
from trader.database.manager import DatabaseManager
from trader.exchange.binance.exchange import BinanceExchange
from trader.exchange.exchange_config import MarginMode
from trader.exchange.user_credentials import (
    attach_user_exchange_context,
    base_exchange_config,
    build_user_exchange_context,
)
from trader.execution.models import ExecutionStatus
from trader.live.auto_execution import is_real_auto_mode
from trader.statistics.stat import BackTraderStat
from trader.strategy.trader_result import parse_trader_result
from trader.task.backtrader_task import BacktestSampleResult, BackTraderTask, build_backtest_sample_spec, process_backtrader, run_backtest_sample
from trader.task.base_task import BaseTask
from trader.task.check_klines_num_task import CheckKlinesNumTask
from trader.task.check_klines_task import CheckKlinesTask
from trader.task.dataset_resolver import DatasetPreparationFailure, DatasetPreparationResult, DatasetResolver
from trader.task.debug_task import DebugTask
from trader.task.import_csv_task import ImportCSVTask
from trader.task.live_startup_self_check import infer_required_margin_mode, task_requires_short_capability
from trader.task.optimization_report import write_optimization_artifacts
from trader.task.optimization_runtime import OptimizationRuntimeStatus, evaluate_abort_reason
from trader.task.task_config import TaskConfig, parse_task_config
from trader.task.task_type import TaskType
from trader.task.trader_task import TraderTask
from trader.task.update_klines_task import UpdateKlinesTask
from trader.utils.symbol_interval import Symbol, SymbolInterval
from trader.utils.task_state import TaskState, TaskStateType


class TaskManager:
    def __init__(
        self,
        cfg: Config,
        log: Logger,
        db_manager: DatabaseManager,
        exchange: BinanceExchange,
    ):
        self.log = log
        self.cfg = cfg
        self.db_manager = db_manager
        self.exchange = exchange
        self._exchange_by_mode: dict[str, BinanceExchange] = {}
        if getattr(exchange, "margin_mode", None) is not None:
            self._exchange_by_mode[exchange.margin_mode.value] = exchange
        self.log.info("Init TaskManager")
        self.tasks: dict[int, BaseTask] = {}
        self.async_tasks = []
        self.latest_si: SymbolInterval | None = None
        self._closing = False

    def _build_task(self, cfg: TaskConfig, exchange: BinanceExchange) -> BaseTask | None:
        if cfg.ttype == TaskType.TRADER:
            return TraderTask(cfg, self.cfg, self.log, self.db_manager, exchange)
        if cfg.ttype == TaskType.BACK_TRADER:
            return BackTraderTask(cfg, self.cfg, self.log, self.db_manager, exchange)
        if cfg.ttype == TaskType.UPDATE_KLINES:
            return UpdateKlinesTask(cfg, self.cfg, self.log, self.db_manager, exchange)
        if cfg.ttype == TaskType.CHECK_KLINES:
            return CheckKlinesTask(cfg, self.cfg, self.log, self.db_manager, exchange)
        if cfg.ttype == TaskType.IMPORT_CSV:
            return ImportCSVTask(cfg, self.cfg, self.log, self.db_manager, exchange)
        if cfg.ttype == TaskType.CHECK_KLINES_NUM:
            return CheckKlinesNumTask(cfg, self.cfg, self.log, self.db_manager, exchange)
        if cfg.ttype == TaskType.DEBUG:
            return DebugTask(cfg, self.cfg, self.log, self.db_manager)
        return None

    def start(self, taskcs: list[TaskConfig] | None = None):
        self.log.info("TaskManager start")
        if taskcs is None and self.cfg.tasks:
            taskcs = parse_task_config(self.cfg.tasks)
        if taskcs is not None:
            required_margin_mode = infer_required_margin_mode(taskcs)
            if getattr(self.exchange, "margin_mode", None) is not None and required_margin_mode.value != self.exchange.margin_mode.value:
                self.log.info(
                    f"TaskManager mixed-mode detected: required_margin_mode={required_margin_mode.value}, "
                    f"default_exchange_margin_mode={self.exchange.margin_mode.value}. Per-task exchange routing enabled."
                )
        if taskcs:
            if len(taskcs) <= 0:
                return None
            return new_add_tasks_msg(taskcs)
        return None

    def stop(self):
        pass

    async def close(self):
        self._closing = True
        closing_states = []
        for task in self.tasks.values():
            task.close()
            closing_states.append(task.ts)

        await asyncio.gather(*self.async_tasks)
        await self._persist_task_states(closing_states)

    def add_tasks(self, taskcs: list[TaskConfig], queue: Queue):

        def on_done(t):
            exc = t.exception()
            if exc:
                self.log.error(f"Exception:{exc}")

        task = asyncio.create_task(self.do_add_tasks(taskcs, queue))
        task.add_done_callback(on_done)
        self.async_tasks.append(task)

    async def do_add_tasks(self, taskcs: list[TaskConfig], queue: Queue):
        if len(taskcs) <= 0:
            self.log.error("Empty task config for add")
            return

        self.log.info(f"Try to add tasks:{len(taskcs)}")
        try:
            await self._ensure_routed_exchanges(taskcs)
            await self._cancel_startup_open_orders(taskcs)
            await self._preflight_live_task_balances(taskcs)

            async_tasks = []
            bttaskcs = []
            for taskc in taskcs:
                if taskc.free < 0:
                    taskc.free = self.cfg.cash

                if taskc.ttype == TaskType.BACK_TRADER:
                    bttaskcs.append(taskc)
                if taskc.symbol_interval:
                    self.latest_si = taskc.symbol_interval

            if len(bttaskcs) > 0:
                async_tasks.append(asyncio.create_task(self.add_backtrader_task(bttaskcs, queue)))

            for taskc in taskcs:
                if taskc.ttype == TaskType.BACK_TRADER:
                    continue
                async_tasks.append(asyncio.create_task(self._call_add_task_after_startup_cleanup(taskc, queue)))

            self.log.info(f"All tasks are created to running:{len(async_tasks)}")
            await asyncio.gather(*async_tasks)

            completed_states = []
            releasable_task_ids = []
            for tc in taskcs:
                task = self.get_task(tc.id)
                if task:
                    if self._closing:
                        continue
                    task.stop()
                    completed_states.append(task.ts)
                    releasable_task_ids.append(tc.id)
                    self.tasks.pop(tc.id)

            await self._persist_task_states(completed_states)
            for task_id in releasable_task_ids:
                await self._release_task_funds(task_id, reason="task_done")
        except Exception as exc:
            persist_exc = None
            try:
                await self._persist_failed_task_states(taskcs, exc)
            except Exception as failed_state_exc:
                persist_exc = failed_state_exc
            for tc in taskcs:
                await self._release_task_funds(tc.id, reason="task_failed")
            if persist_exc is not None:
                raise persist_exc
            raise
        finally:
            if not self.cfg.is_server():
                self.log.info("Try to actively exit")
                await queue.put(new_exit_msg())

    async def _persist_task_states(self, states: list[TaskState]) -> None:
        if not self.db_manager or not getattr(self.db_manager, "task", None):
            return
        if states:
            await self.db_manager.task.add_tasks(states)

    async def _persist_failed_task_states(self, taskcs: list[TaskConfig], exc: Exception) -> None:
        if not taskcs:
            return
        error_message = str(exc)
        failed_states = []
        for tc in taskcs:
            task = self.get_task(tc.id)
            if task is not None:
                state = task.ts
            else:
                state = TaskState(
                    tc.id,
                    self._task_state_name(tc),
                    datetime.now(),
                    commission=getattr(self.cfg, "commission", 0),
                    strategy_start_time=getattr(tc, "start_time", 0),
                    strategy_end_time=getattr(tc, "end_time", 0),
                    initial_cash=getattr(tc, "free", 0) if getattr(tc, "free", -1) >= 0 else getattr(self.cfg, "cash", 0),
                    config_json=self._task_config_json(tc),
                    user_id=getattr(tc, "user_id", None),
                )
            state.state = TaskStateType.FAILED
            state.error_message = error_message
            failed_states.append(state)
        await self._persist_task_states(failed_states)

    def _task_state_name(self, cfg: TaskConfig) -> str:
        symbol_interval = getattr(cfg, "symbol_interval", None)
        symbol_name = symbol_interval.name() if symbol_interval is not None else ""
        return f"{cfg.id}.{cfg.ttype.name}.{symbol_name}"

    def _task_config_json(self, cfg: TaskConfig) -> str:
        return BaseTask(cfg, self.cfg, self.log, self.db_manager).ts.config_json

    def _call_add_task_after_startup_cleanup(self, cfg, queue: Queue):
        add_task = self.add_task
        try:
            params = inspect.signature(add_task).parameters
        except (TypeError, ValueError):
            return add_task(cfg, queue, cancel_startup_orders=False)
        if "cancel_startup_orders" in params or any(param.kind == param.VAR_KEYWORD for param in params.values()):
            return add_task(cfg, queue, cancel_startup_orders=False)
        return add_task(cfg, queue)

    async def add_task(self, cfg, queue: Queue, *, cancel_startup_orders: bool = True):
        task_exchange = await self._exchange_for_task(cfg)
        task = self._build_task(cfg, task_exchange)

        if task is None:
            self.log.error(f"Can't add task:{cfg.to_dict()}")
            return
        if cancel_startup_orders:
            await self._cancel_task_start_open_orders(cfg, task_exchange, reason="task_start")
        self.tasks[task.id()] = task
        self._bind_order_context(cfg, task_exchange)
        await task.start(queue)

    async def recover_task(self, cfg: TaskConfig, queue: Queue):
        await self._restore_recovered_task_runtime_budget(cfg)
        task_exchange = await self._exchange_for_task(cfg)
        task = self._build_task(cfg, task_exchange)

        if task is None:
            self.log.error(f"Can't recover task:{cfg.to_dict()}")
            return

        self.tasks[task.id()] = task
        # Recovery path: the task's exchange orders are already live and valid.
        # Do NOT cancel them — just rebind the order context for new orders.
        self._bind_order_context(cfg, task_exchange)
        runtime = asyncio.create_task(task.start(queue))
        self.async_tasks.append(runtime)

        while True:
            if runtime.done():
                try:
                    await runtime
                except Exception:
                    raise
                return
            if task.ts.is_running():
                return
            await asyncio.sleep(0)

    async def _preflight_live_task_balances(self, taskcs: list[TaskConfig]) -> None:
        for cfg in taskcs:
            requirement = await self._reservation_requirement(cfg)
            if requirement is None:
                continue
            amount = float(requirement["amount"])
            capacity = float(requirement["capacity"])
            if amount > capacity + 1e-12:
                exc = FundReservationError(
                    "insufficient live task balance: "
                    f"task_id={getattr(cfg, 'id', None)} "
                    f"account_key={requirement.get('account_key')} "
                    f"asset={requirement.get('asset')} "
                    f"capacity={capacity} "
                    f"balance={requirement.get('balance')} "
                    f"max_borrowable={requirement.get('max_borrowable')} "
                    f"borrow_limit={requirement.get('borrow_limit')} "
                    f"operable_capacity={requirement.get('operable_capacity')} "
                    f"requested={amount}"
                )
                self.log.error(self._format_reservation_rejection_log(cfg, requirement, exc))
                raise exc
            self._set_task_runtime_budget(cfg, requirement)

    def _set_task_runtime_budget(self, cfg: TaskConfig, requirement: dict, *, remaining: float | None = None) -> None:
        amount = float(requirement["amount"])
        cfg.fund_reservation_account_key = requirement["account_key"]
        cfg.fund_reservation_asset = requirement["asset"]
        cfg.fund_reservation_amount = amount
        cfg.fund_reservation_remaining = amount if remaining is None else max(float(remaining), 0.0)

    async def _restore_recovered_task_runtime_budget(self, cfg: TaskConfig) -> None:
        requirement = await self._reservation_requirement(cfg)
        if requirement is None:
            return
        amount = float(requirement["amount"])
        spent = await self._submitted_entry_notional_for_task(int(cfg.id))
        self._set_task_runtime_budget(cfg, requirement, remaining=max(amount - spent, 0.0))

    async def _submitted_entry_notional_for_task(self, task_id: int) -> float:
        store = getattr(self.db_manager, "execution_state", None)
        if store is None:
            return 0.0
        list_open_by_task = getattr(store, "list_open_by_task", None)
        if not callable(list_open_by_task):
            return 0.0
        records = list_open_by_task(task_id)
        if inspect.isawaitable(records):
            records = await records
        total = 0.0
        for record in records or []:
            if str(getattr(record, "order_role", "")).lower() != "entry":
                continue
            status = getattr(record, "status", None)
            status_value = getattr(status, "value", status)
            if status_value != ExecutionStatus.SUBMITTED.value:
                continue
            notional = self._execution_record_notional(record)
            if notional > 0:
                total += notional
        return total

    def _execution_record_notional(self, record) -> float:
        raw_payload = getattr(record, "raw_payload", None)
        if isinstance(raw_payload, dict):
            for key in ("effective_notional", "notional"):
                value = raw_payload.get(key)
                try:
                    notional = float(value)
                except (TypeError, ValueError):
                    continue
                if notional > 0:
                    return notional
        try:
            quantity = float(getattr(record, "quantity", 0.0) or 0.0)
            price = float(getattr(record, "price", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return max(quantity * price, 0.0)

    def _format_reservation_rejection_log(self, cfg: TaskConfig, requirement: dict, exc: FundReservationError) -> str:
        symbol_interval = getattr(cfg, "symbol_interval", None)
        symbol = symbol_interval.symbol() if symbol_interval is not None else ""
        return (
            "strategy rejected before execution: "
            "rule=requested <= operable_capacity "
            f"task_id={getattr(cfg, 'id', None)} "
            f"symbol={symbol} "
            f"strategy={cfg.strategy_name()} "
            f"live_execution_mode={getattr(cfg, 'live_execution_mode', None)} "
            f"account_key={requirement.get('account_key')} "
            f"market_mode={requirement.get('market_mode')} "
            f"asset={requirement.get('asset')} "
            f"required={requirement.get('amount')} "
            f"balance={requirement.get('balance')} "
            f"max_borrowable={requirement.get('max_borrowable')} "
            f"borrow_limit={requirement.get('borrow_limit')} "
            f"operable_capacity={requirement.get('operable_capacity')} "
            f"reason={exc}"
        )

    def _runtime_live_execution_mode(self, cfg: TaskConfig) -> str:
        return str(getattr(cfg, "live_execution_mode", "auto_trade") or "auto_trade").strip().lower()

    async def _reservation_requirement(self, cfg: TaskConfig) -> dict | None:
        if cfg.ttype != TaskType.TRADER:
            return None
        if not is_real_auto_mode(self._runtime_live_execution_mode(cfg)):
            return None
        if getattr(cfg, "symbol_interval", None) is None:
            return None
        amount = self._reservation_amount(cfg)
        if amount <= 0:
            return None
        exchange = await self._exchange_for_task(cfg)
        asset = str(cfg.symbol_interval.sy.quote).upper()
        capacity_snapshot = self._reservation_capacity_snapshot(cfg, exchange, asset)
        capacity = capacity_snapshot["operable_capacity"]
        return {
            "account_key": await self._reservation_account_key(cfg),
            "exchange": getattr(exchange, "name", lambda: "BINANCE")() if callable(getattr(exchange, "name", None)) else "BINANCE",
            "credential_id": await self._reservation_credential_id(cfg),
            "user_id": getattr(cfg, "user_id", None),
            "task_id": int(cfg.id),
            "asset": asset,
            "amount": amount,
            "capacity": capacity,
            "market_mode": getattr(getattr(exchange, "margin_mode", None), "value", None),
            "balance": capacity_snapshot["balance"],
            "max_borrowable": capacity_snapshot["max_borrowable"],
            "borrow_limit": capacity_snapshot["borrow_limit"],
            "operable_capacity": capacity_snapshot["operable_capacity"],
            "reason": "live_task_start",
        }

    def _reservation_amount(self, cfg: TaskConfig) -> float:
        max_notional = float(getattr(cfg, "live_trade_max_notional", 0.0) or 0.0)
        if max_notional > 0:
            return max_notional
        if getattr(cfg, "free", -1) >= 0:
            return float(cfg.free)
        return float(getattr(self.cfg, "cash", 0.0) or 0.0)

    def _reservation_capacity(self, cfg: TaskConfig, exchange: BinanceExchange, asset: str) -> float:
        return float(self._reservation_capacity_snapshot(cfg, exchange, asset)["operable_capacity"])

    def _reservation_capacity_snapshot(self, cfg: TaskConfig, exchange: BinanceExchange, asset: str) -> dict[str, float | None]:
        balance_reader = getattr(exchange, "get_account_balance", None)
        if not callable(balance_reader):
            raise FundReservationError(f"cannot read exchange balance for reservation: task_id={cfg.id} asset={asset}")
        balance = float(balance_reader(asset) or 0.0)
        snapshot = {
            "balance": balance,
            "max_borrowable": 0.0,
            "borrow_limit": None,
            "operable_capacity": balance,
        }
        if not task_requires_short_capability(cfg):
            return snapshot
        if not bool(getattr(cfg, "live_margin_borrow_precheck", True)):
            return snapshot
        borrow_reader = getattr(exchange, "get_max_borrowable", None)
        if not callable(borrow_reader):
            return snapshot
        payload = borrow_reader(asset, symbol=cfg.symbol_interval.symbol())
        borrowable = self._numeric_payload_value(payload, "amount")
        snapshot["max_borrowable"] = float(borrowable or 0.0)
        snapshot["borrow_limit"] = self._numeric_payload_value(payload, "borrowLimit")
        snapshot["operable_capacity"] = balance + snapshot["max_borrowable"]
        return snapshot

    def _numeric_payload_value(self, payload, key: str) -> float | None:
        value = payload.get(key) if isinstance(payload, dict) else getattr(payload, key, None)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def _reservation_account_key(self, cfg: TaskConfig) -> str:
        credential_id = await self._reservation_credential_id(cfg)
        if credential_id is not None:
            return f"BINANCE:credential:{credential_id}"
        user_id = getattr(cfg, "user_id", None)
        if user_id is not None:
            return f"BINANCE:user:{user_id}:default"
        return "BINANCE:default"

    async def _reservation_credential_id(self, cfg: TaskConfig) -> int | None:
        user_id = getattr(cfg, "user_id", None)
        credential_repo = getattr(self.db_manager, "exchange_credential", None)
        if user_id is None or credential_repo is None:
            return None
        credential = await credential_repo.get_default(user_id, "BINANCE")
        return getattr(credential, "id", None)

    async def _release_task_funds(self, task_id: int, *, reason: str) -> None:
        store = getattr(self.db_manager, "account_fund_reservation", None)
        if store is None:
            return
        try:
            await store.release_task(task_id, reason=reason)
        except Exception as exc:
            self.log.error(f"Failed to release task fund reservation: task_id={task_id} reason={reason} error={exc}")

    async def _exchange_for_task(self, cfg: TaskConfig) -> BinanceExchange:
        if cfg.ttype != TaskType.TRADER:
            return self.exchange
        target_mode = MarginMode.CROSS_MARGIN if task_requires_short_capability(cfg) else MarginMode.SPOT
        chainer_mode = str((getattr(cfg, "strategy_params", {}) or {}).get("chainer_mode", "LONG_ONLY")).strip().upper()
        requires_short_capability = task_requires_short_capability(cfg)
        if getattr(cfg, "user_id", None) is not None:
            routed = await self._exchange_for_user_mode(cfg.user_id, target_mode)
            self.log.info(
                "TaskManager selected execution exchange "
                f"task_id={cfg.id} user_id={cfg.user_id} strategy={cfg.strategy_name()} "
                f"chainer_mode={chainer_mode} requires_short_capability={requires_short_capability} "
                f"target_margin_mode={target_mode.value} actual_margin_mode={getattr(getattr(routed, 'margin_mode', None), 'value', 'unknown')} "
                f"credential_id={getattr(routed, 'credential_id', None)} api_key={getattr(routed, 'masked_api_key', '')}"
            )
            return routed
        if not is_real_auto_mode(self._runtime_live_execution_mode(cfg)):
            return self.exchange
        cached = self._exchange_by_mode.get(target_mode.value)
        if cached is not None:
            self.log.info(
                "TaskManager selected execution exchange "
                f"task_id={cfg.id} user_id={getattr(cfg, 'user_id', None)} strategy={cfg.strategy_name()} "
                f"chainer_mode={chainer_mode} requires_short_capability={requires_short_capability} "
                f"target_margin_mode={target_mode.value} actual_margin_mode={getattr(getattr(cached, 'margin_mode', None), 'value', 'unknown')}"
            )
            return cached
        try:
            routed = self._exchange_for_mode(target_mode)
            self.log.info(
                f"TaskManager created routed exchange for mode={target_mode.value} task_id={cfg.id} strategy={cfg.strategy_name()}"
            )
            self.log.info(
                "TaskManager selected execution exchange "
                f"task_id={cfg.id} user_id={getattr(cfg, 'user_id', None)} strategy={cfg.strategy_name()} "
                f"chainer_mode={chainer_mode} requires_short_capability={requires_short_capability} "
                f"target_margin_mode={target_mode.value} actual_margin_mode={getattr(getattr(routed, 'margin_mode', None), 'value', 'unknown')}"
            )
            return routed
        except Exception as exc:
            self.log.warning(
                f"TaskManager failed to create routed exchange for mode={target_mode.value}, falling back to default exchange: {exc}"
            )
            self.log.info(
                "TaskManager selected execution exchange "
                f"task_id={cfg.id} user_id={getattr(cfg, 'user_id', None)} strategy={cfg.strategy_name()} "
                f"chainer_mode={chainer_mode} requires_short_capability={requires_short_capability} "
                f"target_margin_mode={target_mode.value} "
                f"actual_margin_mode={getattr(getattr(self.exchange, 'margin_mode', None), 'value', 'unknown')} "
                "fallback=true"
            )
            return self.exchange

    async def _exchange_for_user_mode(self, user_id: int, mode: MarginMode) -> BinanceExchange:
        if not self.db_manager or not getattr(self.db_manager, "exchange_credential", None):
            raise RuntimeError("live trading requires a user exchange credential store")
        service_key = getattr(self.cfg, "secret_key", None)
        if not service_key_available(service_key):
            raise RuntimeError("TRADER_SECRET_KEY is required to start user-owned live trading tasks")
        credential = self.db_manager.exchange_credential.get_default(user_id, "BINANCE")
        if inspect.isawaitable(credential):
            credential = await credential
        context = build_user_exchange_context(
            base_cfg=base_exchange_config(self.exchange, self.cfg),
            service_key=service_key,
            credential=credential,
            user_id=user_id,
            margin_mode=mode,
        )
        return attach_user_exchange_context(BinanceExchange(context.cfg, self.log), context)

    async def _ensure_routed_exchanges(self, taskcs: list[TaskConfig]) -> None:
        for tc in taskcs:
            if tc.ttype != TaskType.TRADER:
                continue
            target_mode = MarginMode.CROSS_MARGIN if task_requires_short_capability(tc) else MarginMode.SPOT
            if getattr(tc, "user_id", None) is not None:
                await self._exchange_for_user_mode(tc.user_id, target_mode)
                continue
            if not is_real_auto_mode(self._runtime_live_execution_mode(tc)):
                continue
            _ = self._exchange_by_mode.get(target_mode.value) or self._exchange_for_mode(target_mode)

    def _exchange_for_mode(self, mode: MarginMode) -> BinanceExchange:
        cached = self._exchange_by_mode.get(mode.value)
        if cached is not None:
            return cached
        base_cfg = getattr(self.exchange, "cfg", None)
        if base_cfg is None or not hasattr(base_cfg, "with_margin_mode"):
            return self.exchange
        cloned_cfg = base_cfg.with_margin_mode(mode)
        routed = BinanceExchange(cloned_cfg, self.log)
        self._exchange_by_mode[mode.value] = routed
        return routed

    async def add_backtrader_task(self, cfgs, queue: Queue):
        runtimes = self._optimization_runtimes(cfgs)
        for runtime in runtimes.values():
            runtime.start()

        failures = await self._prepare_backtest_datasets(cfgs, runtimes)
        failed_task_ids = {failure["task_id"] for failure in failures}
        cfg_by_id = {cfg.id: cfg for cfg in cfgs}
        for failure in failures:
            cfg = cfg_by_id.get(failure["task_id"])
            runtime = runtimes.get(cfg.optimization_run_id) if cfg else None
            if runtime:
                runtime.sample_skipped(
                    failure["task_id"],
                    reason=failure.get("reason", "dataset_failed"),
                    dataset_key=failure.get("dataset_key"),
                    message=failure.get("message"),
                )

        aborted_run_ids = self._abort_unhealthy_runtimes(runtimes)
        for run_id in aborted_run_ids:
            failures.append(
                {
                    "task_id": None,
                    "optimization_run_id": run_id,
                    "dataset_key": None,
                    "reason": "run_aborted",
                    "message": runtimes[run_id].status.get("abort_reason") or "optimization run aborted",
                }
            )
        sample_specs = []
        regular_results = []
        task_by_id = {}
        for cfg in cfgs:
            if cfg.id in failed_task_ids:
                continue
            if cfg.optimization_run_id in aborted_run_ids:
                continue
            task = BackTraderTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
            self.tasks[task.id()] = task
            task_by_id[task.id()] = task
            if cfg.optimization_run_id:
                persist_result = BaseTask.start(task, queue)
                if inspect.isawaitable(persist_result):
                    await persist_result
                sample_specs.append(build_backtest_sample_spec(self.cfg, cfg))
                continue

            task_params = await task.start(queue)
            if task_params is None:
                continue
            result = []
            await asyncio.to_thread(
                process_backtrader,
                [self.cfg, task_params[1], task_params[0], cfg, task.ts],
                result,
            )
            regular_results.extend(result)

        sample_records = []
        execution_failures = []
        for msg, logs, _report_record in regular_results:
            for log_str in logs:
                self.log.add_log_buffer(log_str, LogTag.STRATEGY)
            self.log.info(f"Relay process queue message:{msg.name()}", LogTag.STRATEGY)
            await queue.put(msg)

        for sample_spec in sample_specs:
            runtime = runtimes.get(sample_spec.optimization_run_id)
            if runtime:
                runtime.sample_started(sample_spec.task_id)

        sample_results = await self._execute_sample_specs(sample_specs) if sample_specs else []
        for sample_result in sample_results:
            task = task_by_id.get(sample_result.task_id)
            if task is None:
                continue
            runtime = runtimes.get(task.tcfg.optimization_run_id)

            for log_str in sample_result.logs:
                self.log.add_log_buffer(log_str, LogTag.STRATEGY)

            if not sample_result.ok or sample_result.trader_result is None:
                self.log.error(
                    f"Backtest sample failed: task_id={sample_result.task_id}, error={sample_result.error}",
                    LogTag.STRATEGY,
                )
                failure_reason = "sample_timeout" if getattr(sample_result, "timed_out", False) else "execution_failed"
                execution_failures.append(
                    {
                        "task_id": sample_result.task_id,
                        "dataset_key": getattr(task.tcfg.dataset_ref, "dataset_key", None),
                        "reason": failure_reason,
                        "message": sample_result.error or "backtest execution failed",
                    }
                )
                if runtime:
                    if getattr(sample_result, "timed_out", False):
                        runtime.sample_timed_out(
                            sample_result.task_id,
                            message=sample_result.error or "sample execution exceeded timeout budget",
                        )
                    else:
                        runtime.sample_failed(
                            sample_result.task_id,
                            reason="execution_failed",
                            message=sample_result.error or "backtest execution failed",
                        )
                continue

            task.ts.tret = parse_trader_result(sample_result.trader_result)
            msg = new_stat_msg(
                BackTraderStat(task.tcfg.strategy_name(), task.tcfg.symbol_interval.name(), task.ts),
                task.id(),
            )
            self.log.info(f"Relay process queue message:{msg.name()}", LogTag.STRATEGY)
            await queue.put(msg)
            sample_records.append(
                {
                    "task_id": sample_result.task_id,
                    "report": sample_result.report,
                    "report_path": sample_result.report_path,
                }
            )
            if runtime:
                runtime.sample_succeeded(sample_result.task_id)

        self._finalize_optimization_runs(cfgs, sample_records, failures + execution_failures)
        for runtime in runtimes.values():
            if runtime.status["stage"] != "aborted":
                runtime.finish()

    def _abort_unhealthy_runtimes(self, runtimes: dict[str, OptimizationRuntimeStatus]) -> set[str]:
        aborted = set()
        for run_id, runtime in runtimes.items():
            reason = evaluate_abort_reason(
                runtime.status,
                max_failure_rate=float(getattr(self.cfg, "optimization_max_failure_rate", 0.9)),
                min_completed_samples=int(getattr(self.cfg, "optimization_min_completed_samples_for_abort", 50)),
                no_progress_timeout_seconds=float(getattr(self.cfg, "optimization_no_progress_timeout_seconds", 180.0)),
                min_runnable_ratio=float(getattr(self.cfg, "optimization_min_runnable_ratio", 0.1)),
                parallelism_collapse_ratio=float(getattr(self.cfg, "optimization_parallelism_collapse_ratio", 0.25)),
                worker_cpu_efficiency_threshold=float(getattr(self.cfg, "optimization_worker_cpu_efficiency_threshold", 0.1)),
            )
            if reason:
                runtime.abort(reason)
                aborted.add(run_id)
        return aborted

    def _optimization_runtimes(self, cfgs: list[TaskConfig]) -> dict[str, OptimizationRuntimeStatus]:
        runtimes = {}
        for run_id in sorted({cfg.optimization_run_id for cfg in cfgs if cfg.optimization_run_id}):
            run_cfgs = [cfg for cfg in cfgs if cfg.optimization_run_id == run_id]
            dataset_keys = {
                (cfg.symbol_interval.name(), cfg.start_time, cfg.end_time) for cfg in run_cfgs if cfg.ttype == TaskType.BACK_TRADER and not cfg.csv
            }
            runtimes[run_id] = OptimizationRuntimeStatus(
                Path.cwd() / "tmp" / "optimization_runs" / run_id,
                run_id,
                total_samples=len(run_cfgs),
                total_datasets=len(dataset_keys),
                configured_workers=self._sample_max_workers(),
            )
        return runtimes

    def _dataset_prepare_max_workers(self) -> int:
        cpu_count = os.cpu_count() or 1
        return max(1, min(4, cpu_count))

    def _sample_max_workers(self) -> int:
        return max(1, os.cpu_count() or 1)

    def _optimization_dataset_prepare_timeout_seconds(self) -> float:
        return float(getattr(self.cfg, "optimization_dataset_prepare_timeout_seconds", 600.0))

    def _optimization_dataset_download_request_budget(self) -> int:
        return int(getattr(self.cfg, "optimization_dataset_download_request_budget", 2))

    def _optimization_sample_timeout_seconds(self) -> float:
        return float(getattr(self.cfg, "optimization_sample_timeout_seconds", 60.0))

    async def _prepare_dataset_job(
        self,
        resolver: DatasetResolver,
        symbol_interval,
        start_time: int,
        end_time: int,
        allow_download: bool,
        max_download_ranges: int | None = None,
        allow_incomplete_coverage: bool = False,
    ):
        prepare_kwargs = {
            "allow_download": allow_download,
            "max_download_ranges": max_download_ranges,
        }
        if "allow_incomplete_coverage" in inspect.signature(resolver.prepare).parameters:
            prepare_kwargs["allow_incomplete_coverage"] = allow_incomplete_coverage
        return await resolver.prepare(
            symbol_interval,
            start_time,
            end_time,
            **prepare_kwargs,
        )

    async def _prepare_backtest_datasets(
        self,
        cfgs: list[TaskConfig],
        runtimes: dict[str, OptimizationRuntimeStatus] | None = None,
    ) -> list[dict]:
        if not cfgs:
            return []

        prepared_results = {}
        failures = []
        dataset_jobs = {}
        dataset_run_ids = {}

        for cfg in cfgs:
            if cfg.ttype != TaskType.BACK_TRADER or cfg.csv:
                continue
            dataset_key = (cfg.symbol_interval.name(), cfg.start_time, cfg.end_time)
            if dataset_key not in dataset_jobs:
                dataset_jobs[dataset_key] = (
                    cfg.symbol_interval,
                    cfg.start_time,
                    cfg.end_time,
                    bool(cfg.auto_download),
                    cfg.optimization_run_id is not None,
                )
            if cfg.optimization_run_id:
                dataset_run_ids.setdefault(dataset_key, set()).add(cfg.optimization_run_id)

        semaphore = asyncio.Semaphore(self._dataset_prepare_max_workers())
        dataset_timeout_seconds = self._optimization_dataset_prepare_timeout_seconds()
        if dataset_jobs:
            self.log.info(
                "Optimization dataset preparation: "
                f"datasets={len(dataset_jobs)} "
                f"max_workers={self._dataset_prepare_max_workers()} "
                f"timeout={dataset_timeout_seconds:.1f}s"
            )

        async def run_job(dataset_key, job):
            async with semaphore:
                resolver = DatasetResolver(self.db_manager, self.exchange, self.log)
                symbol_interval, start_time, end_time, allow_download, allow_incomplete_coverage = job
                status_dataset_key = f"{symbol_interval.name()}|{start_time}|{end_time}"
                self.log.info(
                    f"Dataset preparation started: {status_dataset_key} "
                    f"allow_download={bool(allow_download)} "
                    f"allow_incomplete_coverage={bool(allow_incomplete_coverage)}"
                )
                for run_id in dataset_run_ids.get(dataset_key, set()):
                    runtime = (runtimes or {}).get(run_id)
                    if runtime:
                        runtime.dataset_started(status_dataset_key)
                try:
                    prepare_kwargs = {}
                    if "allow_incomplete_coverage" in inspect.signature(self._prepare_dataset_job).parameters:
                        prepare_kwargs["allow_incomplete_coverage"] = bool(allow_incomplete_coverage)
                    prepared_results[dataset_key] = await asyncio.wait_for(
                        self._prepare_dataset_job(
                            resolver,
                            symbol_interval,
                            start_time,
                            end_time,
                            allow_download,
                            self._optimization_dataset_download_request_budget() if allow_download else None,
                            **prepare_kwargs,
                        ),
                        timeout=dataset_timeout_seconds if allow_download else None,
                    )
                except TimeoutError:
                    prepared_results[dataset_key] = DatasetPreparationResult(
                        ok=False,
                        failure=DatasetPreparationFailure(
                            dataset_key=f"{symbol_interval.name()}|{start_time}|{end_time}",
                            reason="dataset_timeout",
                            message="dataset preparation exceeded optimization timeout budget",
                        ),
                    )
                result = prepared_results[dataset_key]
                if result.ok:
                    self.log.info(f"Dataset preparation finished: {status_dataset_key} status=ok")
                else:
                    reason = result.failure.reason if result.failure else "dataset_failed"
                    self.log.warning(f"Dataset preparation finished: {status_dataset_key} status=failed reason={reason}")
                for run_id in dataset_run_ids.get(dataset_key, set()):
                    runtime = (runtimes or {}).get(run_id)
                    if not runtime:
                        continue
                    if result.ok:
                        runtime.dataset_succeeded(status_dataset_key)
                    elif result.failure and result.failure.reason == "dataset_timeout":
                        runtime.dataset_timed_out(status_dataset_key, message=result.failure.message)
                    else:
                        runtime.dataset_failed(
                            status_dataset_key,
                            reason=result.failure.reason if result.failure else "dataset_failed",
                            message=result.failure.message if result.failure else None,
                        )

        tasks = {asyncio.create_task(run_job(dataset_key, job)): dataset_key for dataset_key, job in dataset_jobs.items()}
        heartbeat_seconds = 15.0
        while tasks:
            done, pending = await asyncio.wait(tasks.keys(), timeout=heartbeat_seconds, return_when=asyncio.FIRST_COMPLETED)
            for finished in done:
                tasks.pop(finished, None)
                finished.result()
            if pending:
                prepared = len(prepared_results)
                total = len(dataset_jobs)
                running = len(pending)
                sample = sorted(
                    (f"{key[0]}|{key[1]}|{key[2]}" for key in list(tasks.values())[:5]),
                )
                suffix = f" examples={sample}" if sample else ""
                self.log.info(f"Dataset preparation progress: prepared={prepared}/{total} running={running}{suffix}")

        for cfg in cfgs:
            if cfg.ttype != TaskType.BACK_TRADER or cfg.csv:
                continue
            dataset_key = (cfg.symbol_interval.name(), cfg.start_time, cfg.end_time)
            result = prepared_results[dataset_key]
            if result.ok:
                cfg.dataset_ref = result.dataset_ref
                continue

            failures.append(
                {
                    "task_id": cfg.id,
                    "dataset_key": result.failure.dataset_key,
                    "reason": result.failure.reason,
                    "message": result.failure.message,
                }
            )

        return failures

    async def _execute_sample_specs(self, sample_specs):
        if not sample_specs:
            return []
        return await asyncio.to_thread(self._execute_sample_specs_sync, sample_specs)

    def _execute_sample_specs_sync(self, sample_specs):
        results = []
        with ProcessPoolExecutor(max_workers=self._sample_max_workers()) as executor:
            futures = [(spec, executor.submit(run_backtest_sample, spec)) for spec in sample_specs]
            for spec, future in futures:
                try:
                    results.append(future.result(timeout=self._optimization_sample_timeout_seconds()))
                except FutureTimeoutError:
                    future.cancel()
                    results.append(
                        BacktestSampleResult(
                            ok=False,
                            task_id=spec.task_id,
                            trader_result=None,
                            logs=[],
                            report=None,
                            report_path=None,
                            error="sample execution exceeded timeout budget",
                            timed_out=True,
                        )
                    )
        return results

    def _finalize_optimization_runs(self, cfgs: list[TaskConfig], sample_records: list[dict], failures: list[dict]):
        task_by_id = {cfg.id: cfg for cfg in cfgs}
        run_ids = sorted({cfg.optimization_run_id for cfg in cfgs if cfg.optimization_run_id})
        if not run_ids:
            return

        for run_id in run_ids:
            run_reports = []
            for record in sample_records:
                report = record.get("report")
                if not report or report.get("optimization_run_id") != run_id:
                    continue
                enriched_report = dict(report)
                if record.get("report_path"):
                    enriched_report["report_path"] = record["report_path"]
                run_reports.append(enriched_report)

            run_failures = []
            for failure in failures:
                if failure.get("optimization_run_id") == run_id:
                    run_failures.append(failure)
                    continue
                task = task_by_id.get(failure.get("task_id"))
                if task and task.optimization_run_id == run_id:
                    run_failures.append(failure)

            write_optimization_artifacts(Path.cwd(), run_id, run_reports, run_failures)

    def get_task(self, id: int) -> BaseTask | None:
        if id in self.tasks:
            return self.tasks[id]
        return None

    def has_task(self, id: int) -> bool:
        return self.get_task(id) is not None

    def remove_task(self, id: int) -> BaseTask | None:
        if id in self.tasks:
            ret: BaseTask = self.tasks.pop(id)
            if ret:
                self.log.info(f"Remove task:id={id}")
                return ret
        return None

    def close_task(self, id: int, user_id: int | None = None):
        task = self.get_task(id)
        if task:
            if user_id is not None and getattr(task.ts, "user_id", None) != user_id:
                return False
            # Keep task-state semantics consistent with UI/API expectations:
            # stopping a running task should immediately transition RUNNING -> DONE.
            task.stop()
            return True
        return False

    async def close_task_state(self, id: int, user_id: int | None = None):
        task = self.get_task(id)
        if task:
            if user_id is not None and getattr(task.ts, "user_id", None) != user_id:
                return False
            task.stop()
            si = getattr(task.tcfg, "symbol_interval", None)
            fallback_symbols = [si.sy] if si is not None else []
            await self._cancel_open_orders_for_task(
                getattr(task.tcfg, "id", id),
                getattr(task, "exchange", None),
                reason="task_closed",
                fallback_symbols=fallback_symbols,
            )
            await self._persist_task_states([task.ts])
            await self._release_task_funds(id, reason="task_closed")
            return True

        task_store = getattr(self.db_manager, "task", None)
        if task_store is None:
            return False
        if user_id is not None:
            state = await task_store.get_task_for_user(id, user_id)
        else:
            state = await task_store.get_task(id)
        if state is None or not state.is_running():
            return False
        cfg = self._task_config_from_state(state)
        if cfg is not None:
            task_exchange = await self._exchange_for_task(cfg)
            si = getattr(cfg, "symbol_interval", None)
            await self._cancel_open_orders_for_task(
                id,
                task_exchange,
                reason="task_closed",
                fallback_symbols=[si.sy] if si is not None else [],
            )
        state.state = TaskStateType.DONE
        await self._persist_task_states([state])
        await self._release_task_funds(id, reason="task_closed")
        return True

    def _task_config_from_state(self, state: TaskState) -> TaskConfig | None:
        config_json = str(getattr(state, "config_json", "") or "").strip()
        if not config_json:
            return None
        try:
            taskcs = parse_task_config(config_json)
        except Exception as exc:
            self.log.error(f"task state config parse failed: task_id={getattr(state, 'id', None)} error={exc}")
            return None
        for cfg in taskcs:
            if int(getattr(cfg, "id", 0) or 0) == int(getattr(state, "id", 0) or 0):
                return cfg
        return taskcs[0] if taskcs else None

    def del_task(self, id: int, user_id: int | None = None):
        task = self.get_task(id)
        if task:
            if user_id is not None and getattr(task.ts, "user_id", None) != user_id:
                return False
            task.close()
            while self.has_task(id):
                sleep(self.log, 1)

        return self.db_manager.task.del_task(id)

    async def get_task_state(self, id: int, user_id: int | None = None) -> TaskState | None:
        task = self.get_task(id)
        if task:
            if user_id is not None and getattr(task.ts, "user_id", None) != user_id:
                return None
            return task.ts
        if self.db_manager:
            if user_id is not None:
                return await self.db_manager.task.get_task_for_user(id, user_id)
            return await self.db_manager.task.get_task(id)

        return None

    async def get_all_task_state(self, user_id: int | None = None) -> list[TaskState]:
        ret: list[TaskState] = []
        for ts in self.tasks.values():
            if user_id is not None and getattr(ts.ts, "user_id", None) != user_id:
                continue
            ret.append(ts.ts)

        if self.db_manager:
            tss = await self.db_manager.task.get_all_tasks_for_user(user_id) if user_id is not None else await self.db_manager.task.get_all_tasks()
            for ts in tss:
                if self.has_task(ts.id):
                    continue
                ret.append(ts)

        return ret

    async def _cancel_startup_open_orders(self, taskcs: list[TaskConfig]) -> None:
        seen: set[tuple[int, str]] = set()
        for cfg in taskcs:
            if getattr(cfg, "ttype", None) != TaskType.TRADER:
                continue
            task_exchange = await self._exchange_for_task(cfg)
            await self._cancel_task_start_open_orders(cfg, task_exchange, reason="task_start", seen=seen)

    async def _cancel_task_start_open_orders(
        self,
        cfg,
        exchange,
        *,
        reason: str,
        seen: set[tuple[int, str]] | None = None,
    ) -> None:
        for task in self._running_tasks_for_cleanup(cfg):
            si = getattr(getattr(task, "tcfg", None), "symbol_interval", None)
            task_exchange = getattr(task, "exchange", None) or exchange
            await self._cancel_open_orders_for_task(
                getattr(getattr(task, "tcfg", None), "id", None),
                task_exchange,
                reason=reason,
                fallback_symbols=[si.sy] if si is not None else [],
                seen=seen,
            )

    def _running_tasks_for_cleanup(self, cfg) -> list[BaseTask]:
        tasks: list[BaseTask] = []
        for task in self.tasks.values():
            if not self._task_is_running(task):
                continue
            if not self._same_cleanup_account(cfg, task):
                continue
            tasks.append(task)
        return tasks

    def _task_is_running(self, task) -> bool:
        state = getattr(task, "ts", None)
        is_running = getattr(state, "is_running", None)
        if callable(is_running):
            return bool(is_running())
        return True

    def _same_cleanup_account(self, cfg, task) -> bool:
        running_cfg = getattr(task, "tcfg", None)
        cfg_user_id = getattr(cfg, "user_id", None)
        running_user_id = getattr(running_cfg, "user_id", None)
        if cfg_user_id is not None or running_user_id is not None:
            return cfg_user_id == running_user_id
        return True

    def _cancel_all_open_orders(self, cfg, exchange, *, reason: str) -> None:
        """Cancel all open orders for the task's symbol on the exchange.

        One live task runs per account at any time, so every open order on the
        exchange belongs to this task. Failures are logged but never propagated.
        """
        si = getattr(cfg, "symbol_interval", None)
        if si is None:
            return
        self._cancel_open_orders_for_symbols([si.sy], exchange, reason=reason, task_id=getattr(cfg, "id", None))

    async def _cancel_open_orders_for_task(
        self,
        task_id,
        exchange,
        *,
        reason: str,
        fallback_symbols=None,
        seen: set[tuple[int, str]] | None = None,
    ) -> bool:
        if task_id is None:
            self._cancel_open_orders_for_symbols(fallback_symbols or [], exchange, reason=reason, task_id=task_id, seen=seen)
            return False

        records = await self._open_execution_records_for_task(int(task_id))
        if not records:
            self._cancel_open_orders_for_symbols(fallback_symbols or [], exchange, reason=reason, task_id=task_id, seen=seen)
            return False

        fallback_for_incomplete_records: list[Symbol] = []
        cancel_order = getattr(exchange, "cancel_order", None)
        for record in records:
            symbol = self._symbol_from_value(getattr(record, "symbol", None))
            if symbol is None:
                continue
            order_ids = self._record_exchange_order_ids(record)
            if not order_ids or not callable(cancel_order):
                fallback_for_incomplete_records.append(symbol)
                continue
            for order_id in order_ids:
                key = (id(exchange), f"{symbol.name()}:{order_id}")
                if seen is not None:
                    if key in seen:
                        continue
                    seen.add(key)
                try:
                    self.log.info(f"cancel_order: reason={reason} task_id={task_id} symbol={symbol.name()} order_id={order_id}")
                    result = cancel_order(symbol, order_id)
                    if inspect.isawaitable(result):
                        await result
                    await self._mark_execution_record_canceled(record)
                except Exception as exc:
                    self.log.error(
                        f"cancel_order failed: reason={reason} task_id={task_id} symbol={symbol.name()} order_id={order_id} error={exc}"
                    )

        self._cancel_open_orders_for_symbols(
            fallback_for_incomplete_records,
            exchange,
            reason=reason,
            task_id=task_id,
            seen=seen,
        )
        return True

    async def _open_execution_records_for_task(self, task_id: int):
        store = getattr(self.db_manager, "execution_state", None)
        list_open_by_task = getattr(store, "list_open_by_task", None)
        if not callable(list_open_by_task):
            return []
        records = list_open_by_task(task_id)
        if inspect.isawaitable(records):
            records = await records
        if isinstance(records, list):
            return records
        return list(records or [])

    def _record_exchange_order_ids(self, record) -> list[str]:
        values: list[str] = []
        raw = str(getattr(record, "exchange_order_id", "") or "").strip()
        if raw:
            values.extend(raw.split(","))
        raw_payload = getattr(record, "raw_payload", None)
        if isinstance(raw_payload, dict):
            for key in ("orderId", "order_id", "clientOrderId", "id"):
                value = raw_payload.get(key)
                if value is not None:
                    values.append(str(value))
        ret: list[str] = []
        seen: set[str] = set()
        for value in values:
            order_id = str(value or "").strip()
            if not order_id or order_id in seen:
                continue
            seen.add(order_id)
            ret.append(order_id)
        return ret

    async def _mark_execution_record_canceled(self, record) -> None:
        store = getattr(self.db_manager, "execution_state", None)
        save = getattr(store, "save", None)
        if not callable(save) or not hasattr(record, "with_updates"):
            return
        updated = record.with_updates(status=ExecutionStatus.CANCELED, updated_at=int(datetime.now().timestamp()))
        result = save(updated)
        if inspect.isawaitable(result):
            await result

    def _cancel_open_orders_for_symbols(
        self,
        symbols,
        exchange,
        *,
        reason: str,
        task_id=None,
        seen: set[tuple[int, str]] | None = None,
    ) -> None:
        cancel = getattr(exchange, "cancel_all_open_orders", None)
        if not callable(cancel):
            return
        for symbol in self._dedupe_symbols(symbols):
            symbol_name = symbol.name()
            if not symbol_name:
                continue
            key = (id(exchange), symbol_name)
            if seen is not None:
                if key in seen:
                    continue
                seen.add(key)
            try:
                self.log.info(f"cancel_all_open_orders: reason={reason} task_id={task_id} symbol={symbol_name}")
                cancel(symbol)
            except Exception as exc:
                self.log.error(f"cancel_all_open_orders failed: reason={reason} task_id={task_id} symbol={symbol_name} error={exc}")

    def _configured_cleanup_symbols(self) -> list[Symbol]:
        raw = getattr(self.cfg, "live_order_cleanup_symbols", None)
        if raw is None:
            return []
        if isinstance(raw, str):
            values = [item for item in raw.split(",")]
        elif isinstance(raw, (list, tuple, set)):
            values = list(raw)
        else:
            return []
        return self._symbols_from_values(values)

    def _symbols_from_values(self, values) -> list[Symbol]:
        return self._dedupe_symbols(self._symbol_from_value(value) for value in values)

    def _dedupe_symbols(self, symbols) -> list[Symbol]:
        ret: list[Symbol] = []
        seen: set[str] = set()
        for symbol in symbols or []:
            if symbol is None:
                continue
            normalized = self._symbol_from_value(symbol)
            if normalized is None or normalized.is_empty():
                continue
            name = normalized.name()
            if name in seen:
                continue
            seen.add(name)
            ret.append(normalized)
        return ret

    def _symbol_from_value(self, value) -> Symbol | None:
        if isinstance(value, Symbol):
            return value
        sy = getattr(value, "sy", None)
        if isinstance(sy, Symbol):
            return sy
        text = str(value or "").strip().upper()
        if not text:
            return None
        text = text.replace("/", "-").replace("_", "-")
        if "-" in text:
            return Symbol(text)
        for quote in ("FDUSD", "USDT", "USDC", "BUSD", "TUSD", "USDP", "DAI", "BTC", "ETH", "BNB", "EUR", "TRY", "USD"):
            if text.endswith(quote) and len(text) > len(quote):
                return Symbol(f"{text[:-len(quote)]}-{quote}")
        return None

    def _bind_order_context(self, cfg, exchange) -> None:
        """Propagate task_id / strategy_name to the ccxt driver so orders carry clientOrderId."""
        bind = getattr(exchange, "bind_order_context", None)
        if callable(bind):
            bind(task_id=getattr(cfg, "id", None), strategy_name=cfg.strategy_name() if callable(getattr(cfg, "strategy_name", None)) else None)
            return
        # Reach into the nested ccxt_driver if the exchange itself doesn't expose the method.
        driver = getattr(exchange, "ccxt_driver", None)
        bind = getattr(driver, "bind_order_context", None)
        if callable(bind):
            bind(task_id=getattr(cfg, "id", None), strategy_name=cfg.strategy_name() if callable(getattr(cfg, "strategy_name", None)) else None)
