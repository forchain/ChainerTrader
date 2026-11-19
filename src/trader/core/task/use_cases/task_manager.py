import asyncio
import inspect
import os
from asyncio import Queue
from datetime import datetime
from typing import Any

from trader.core.exchange.domain import MarginMode
from trader.core.exchange.interfaces import ExchangeFactory
from trader.core.exchange.use_cases import RouteExchangeForTask, base_exchange_config
from trader.core.execution.interfaces import ExecutionGatewayFactory
from trader.core.execution.use_cases import is_real_auto_mode
from trader.core.identity.interfaces import SecretCipherFactory
from trader.core.optimization.interfaces import OptimizationRunnerFactory, OptimizationRuntimeStatusFactory
from trader.core.optimization.use_cases.parameter_optimization import RunParameterOptimizationUseCase
from trader.core.shared.async_utils import sleep
from trader.core.shared.config import Config
from trader.core.shared.domain import Symbol, SymbolInterval
from trader.core.shared.interfaces import LoggerPort
from trader.core.shared.logging import LogTag
from trader.core.shared.messages import new_add_tasks_msg, new_exit_msg, new_stat_msg
from trader.core.strategy.domain.trader_result import parse_trader_result
from trader.core.task.config import TaskConfig
from trader.core.task.config_codec import TaskConfigCodec
from trader.core.task.domain import TaskState, TaskStateType, TaskType, task_requires_short_capability, task_state_name
from trader.core.task.interfaces import TaskConfigSourceLoader, TaskEventPublisher, TaskRunnerFactory
from trader.core.task.stats import BackTraderStat
from trader.core.task.use_cases import (
    CancelTaskOpenOrders,
    CleanupRunningTasksBeforeStart,
    PreflightLiveTaskFunds,
    ReleaseTaskFunds,
    RestoreRecoveredTaskBudget,
    StopTask,
    StopUserRunningTasks,
    symbol_from_value,
)
from trader.core.task.use_cases.startup_self_check import infer_required_margin_mode


class _NullBacktestRunner:
    """Placeholder runner for finalize-only optimization calls."""

    async def prepare_datasets(self, configs, runtimes=None) -> list[dict]:
        return []

    async def execute_samples(self, sample_specs) -> list[Any]:
        return []


class TaskManager:
    def __init__(
        self,
        cfg: Config,
        log: LoggerPort,
        db_manager: Any = None,
        exchange: Any = None,
        event_publisher: TaskEventPublisher | None = None,
        *,
        task_runner_factory: TaskRunnerFactory | None = None,
        task_config_loader: TaskConfigSourceLoader | None = None,
        exchange_factory: ExchangeFactory | None = None,
        report_store: Any = None,
        optimization_runner_factory: OptimizationRunnerFactory | None = None,
        runtime_status_factory: OptimizationRuntimeStatusFactory | None = None,
        cipher_factory: SecretCipherFactory | None = None,
        execution_gateway_factory: ExecutionGatewayFactory | None = None,
    ):
        self.log = log
        self.cfg = cfg
        self.db_manager = db_manager
        self.exchange = exchange
        self.event_publisher = event_publisher
        self._task_runner_factory = task_runner_factory
        self._task_config_loader = task_config_loader
        self._exchange_factory = exchange_factory
        self._report_store = report_store
        self._optimization_runner_factory = optimization_runner_factory
        self._runtime_status_factory = runtime_status_factory
        self._cipher_factory = cipher_factory
        self._execution_gateway_factory = execution_gateway_factory
        self._exchange_by_mode: dict[str, Any] = {}
        if getattr(exchange, "margin_mode", None) is not None:
            self._exchange_by_mode[exchange.margin_mode.value] = exchange
        self.log.info("Init TaskManager")
        self.tasks: dict[int, Any] = {}
        self.async_tasks = []
        self.latest_si: SymbolInterval | None = None
        self._closing = False

    def _build_task(self, cfg: TaskConfig, exchange: Any) -> Any | None:
        if self._task_runner_factory is None:
            self.log.error(f"No task runner factory configured for task:{cfg.to_dict()}")
            return None
        return self._task_runner_factory.build(cfg, exchange)

    def start(self, taskcs: list[TaskConfig] | None = None):
        self.log.info("TaskManager start")
        if taskcs is None and self.cfg.tasks:
            min_notional = getattr(self.cfg, "min_live_trade_notional", 11.0)
            source_text = self._task_config_loader.read_source_text(self.cfg.tasks) if self._task_config_loader else self.cfg.tasks
            taskcs = TaskConfigCodec.from_input(source_text, min_live_trade_notional=min_notional)
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
        return task_state_name(cfg)

    def _task_config_json(self, cfg: TaskConfig) -> str:
        initial_cash = cfg.free if getattr(cfg, "free", -1) >= 0 else getattr(self.cfg, "cash", 0)
        state = TaskConfigCodec.to_task_state(
            cfg,
            name=TaskConfigCodec.state_name(cfg),
            commission=getattr(self.cfg, "commission", 0),
            initial_cash=initial_cash,
        )
        return state.config_json

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

    def _preflight_use_case(self) -> PreflightLiveTaskFunds:
        return PreflightLiveTaskFunds(
            exchange_resolver=self._exchange_for_task,
            account_key_resolver=self._reservation_account_key,
            credential_id_resolver=self._reservation_credential_id,
            default_cash=float(getattr(self.cfg, "cash", 0.0) or 0.0),
            log=self.log,
        )

    async def _preflight_live_task_balances(self, taskcs: list[TaskConfig]) -> None:
        await self._preflight_use_case().execute(taskcs)

    async def _restore_recovered_task_runtime_budget(self, cfg: TaskConfig) -> None:
        restore = RestoreRecoveredTaskBudget(
            execution_state_store=getattr(self.db_manager, "execution_state", None),
            exchange_resolver=self._exchange_for_task,
            account_key_resolver=self._reservation_account_key,
            credential_id_resolver=self._reservation_credential_id,
            default_cash=float(getattr(self.cfg, "cash", 0.0) or 0.0),
        )
        await restore.execute(cfg)

    def _runtime_live_execution_mode(self, cfg: TaskConfig) -> str:
        return str(getattr(cfg, "live_execution_mode", "auto_trade") or "auto_trade").strip().lower()

    async def _reservation_requirement(self, cfg: TaskConfig) -> dict | None:
        return await self._preflight_use_case().build_requirement(cfg)

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
        await ReleaseTaskFunds(store, log=self.log).execute(task_id, reason=reason)

    async def _exchange_for_task(self, cfg: TaskConfig) -> Any:
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
            self.log.info(f"TaskManager created routed exchange for mode={target_mode.value} task_id={cfg.id} strategy={cfg.strategy_name()}")
            self.log.info(
                "TaskManager selected execution exchange "
                f"task_id={cfg.id} user_id={getattr(cfg, 'user_id', None)} strategy={cfg.strategy_name()} "
                f"chainer_mode={chainer_mode} requires_short_capability={requires_short_capability} "
                f"target_margin_mode={target_mode.value} actual_margin_mode={getattr(getattr(routed, 'margin_mode', None), 'value', 'unknown')}"
            )
            return routed
        except Exception as exc:
            self.log.warning(f"TaskManager failed to create routed exchange for mode={target_mode.value}, falling back to default exchange: {exc}")
            self.log.info(
                "TaskManager selected execution exchange "
                f"task_id={cfg.id} user_id={getattr(cfg, 'user_id', None)} strategy={cfg.strategy_name()} "
                f"chainer_mode={chainer_mode} requires_short_capability={requires_short_capability} "
                f"target_margin_mode={target_mode.value} "
                f"actual_margin_mode={getattr(getattr(self.exchange, 'margin_mode', None), 'value', 'unknown')} "
                "fallback=true"
            )
            return self.exchange

    async def _exchange_for_user_mode(self, user_id: int, mode: MarginMode) -> Any:
        service_key = getattr(self.cfg, "secret_key", None)
        cipher = self._cipher_factory(service_key) if self._cipher_factory is not None else None
        exchange_factory = self._exchange_factory or (lambda config, log=None: self.exchange)
        route = RouteExchangeForTask(
            getattr(self.db_manager, "exchange_credential", None),
            base_cfg=base_exchange_config(self.exchange, self.cfg),
            cipher=cipher,
            exchange_factory=lambda config: exchange_factory(config, self.log),
        )
        return await route.execute(user_id, margin_mode=mode)

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

    def _exchange_for_mode(self, mode: MarginMode) -> Any:
        cached = self._exchange_by_mode.get(mode.value)
        if cached is not None:
            return cached
        base_cfg = getattr(self.exchange, "cfg", None)
        if self._exchange_factory is None or base_cfg is None or not hasattr(base_cfg, "with_margin_mode"):
            return self.exchange
        cloned_cfg = base_cfg.with_margin_mode(mode)
        routed = self._exchange_factory(cloned_cfg, self.log)
        self._exchange_by_mode[mode.value] = routed
        return routed

    def _optimization_backtest_runner(self) -> Any:
        if self._optimization_runner_factory is None:
            raise ValueError("TaskManager requires an optimization_runner_factory for optimization runs")
        return self._optimization_runner_factory(
            prepare_dataset_job_fn=self._prepare_dataset_job,
            sample_max_workers=self._sample_max_workers(),
            dataset_prepare_max_workers=self._dataset_prepare_max_workers(),
            dataset_prepare_timeout_seconds=self._optimization_dataset_prepare_timeout_seconds(),
            dataset_download_request_budget=self._optimization_dataset_download_request_budget(),
            sample_timeout_seconds=self._optimization_sample_timeout_seconds(),
        )

    def _optimization_use_case(self, backtest_runner=None) -> RunParameterOptimizationUseCase:
        if backtest_runner is None:
            backtest_runner = self._optimization_backtest_runner()
        return RunParameterOptimizationUseCase(
            backtest_runner=backtest_runner,
            report_store=self._report_store,
            runtime_factory=self._runtime_status_factory,
            max_workers=self._sample_max_workers(),
            abort_thresholds={
                "max_failure_rate": float(getattr(self.cfg, "optimization_max_failure_rate", 0.9)),
                "min_completed_samples": int(getattr(self.cfg, "optimization_min_completed_samples_for_abort", 50)),
                "no_progress_timeout_seconds": float(getattr(self.cfg, "optimization_no_progress_timeout_seconds", 180.0)),
                "min_runnable_ratio": float(getattr(self.cfg, "optimization_min_runnable_ratio", 0.1)),
                "parallelism_collapse_ratio": float(getattr(self.cfg, "optimization_parallelism_collapse_ratio", 0.25)),
                "worker_cpu_efficiency_threshold": float(getattr(self.cfg, "optimization_worker_cpu_efficiency_threshold", 0.1)),
            },
        )

    async def add_backtrader_task(self, cfgs, queue: Queue):
        if self._task_runner_factory is None:
            raise ValueError("TaskManager requires a task_runner_factory for backtest tasks")
        task_by_id: dict[int, Any] = {}

        class _TaskManagerRunnerBridge:
            def __init__(self, manager: TaskManager):
                self.manager = manager

            async def prepare_datasets(self, configs, runtimes=None):
                return await self.manager._prepare_backtest_datasets(configs, runtimes)

            async def execute_samples(self, sample_specs):
                return await self.manager._execute_sample_specs(sample_specs)

        async def _on_sample_task_registered(cfg):
            task = self._task_runner_factory.build(cfg, self.exchange)
            if task is None:
                return
            self.tasks[task.id()] = task
            task_by_id[task.id()] = task
            task.ts.state = TaskStateType.RUNNING
            await self._persist_task_states([task.ts])

        async def _on_regular_task(cfg):
            task = self._task_runner_factory.build(cfg, self.exchange)
            if task is None:
                return
            self.tasks[task.id()] = task
            task_by_id[task.id()] = task
            await self._task_runner_factory.run_backtest_task(task, queue)

        async def _on_sample_failure(cfg, sample_result):
            task = task_by_id.get(sample_result.task_id)
            if task is not None:
                for log_str in sample_result.logs:
                    self.log.add_log_buffer(log_str, LogTag.STRATEGY)
            self.log.error(
                f"Backtest sample failed: task_id={sample_result.task_id}, error={sample_result.error}",
                LogTag.STRATEGY,
            )

        async def _on_sample_result(cfg, sample_result):
            task = task_by_id.get(sample_result.task_id)
            if task is None:
                return
            for log_str in sample_result.logs:
                self.log.add_log_buffer(log_str, LogTag.STRATEGY)
            task.ts.tret = parse_trader_result(sample_result.trader_result)
            msg = new_stat_msg(
                BackTraderStat(task.tcfg.strategy_name(), task.tcfg.symbol_interval.name(), task.ts),
                task.id(),
            )
            self.log.info(f"Relay process queue message:{msg.name()}", LogTag.STRATEGY)
            await queue.put(msg)

        use_case = self._optimization_use_case(backtest_runner=_TaskManagerRunnerBridge(self))
        await use_case.execute(
            cfgs,
            sample_spec_builder=lambda cfg: self._task_runner_factory.build_sample_spec(cfg),
            on_regular_task=_on_regular_task,
            on_sample_task_registered=_on_sample_task_registered,
            on_sample_result=_on_sample_result,
            on_sample_failure=_on_sample_failure,
            finalize_cb=self._finalize_optimization_runs,
        )

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
        resolver: Any,
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
        runtimes: dict | None = None,
    ) -> list[dict]:
        return await self._optimization_backtest_runner().prepare_datasets(cfgs, runtimes)

    async def _execute_sample_specs(self, sample_specs):
        if not sample_specs:
            return []
        return await asyncio.to_thread(self._execute_sample_specs_sync, sample_specs)

    def _execute_sample_specs_sync(self, sample_specs):
        return self._optimization_backtest_runner().execute_samples_sync(sample_specs)

    def _finalize_optimization_runs(self, cfgs: list[TaskConfig], sample_records: list[dict], failures: list[dict]):
        if not any(getattr(cfg, "optimization_run_id", None) for cfg in cfgs):
            return
        if self._report_store is None:
            raise ValueError("TaskManager requires a report_store to finalize optimization runs")
        self._optimization_use_case(backtest_runner=_NullBacktestRunner()).finalize_runs(cfgs, sample_records, failures)

    def get_task(self, id: int) -> Any | None:
        if id in self.tasks:
            return self.tasks[id]
        return None

    def has_task(self, id: int) -> bool:
        return self.get_task(id) is not None

    def remove_task(self, id: int) -> Any | None:
        if id in self.tasks:
            ret: Any = self.tasks.pop(id)
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

    def _stop_task_use_case(self) -> StopTask:
        return StopTask(
            task_repository=getattr(self.db_manager, "task", None),
            fund_reservation_store=getattr(self.db_manager, "account_fund_reservation", None),
            execution_state_store=getattr(self.db_manager, "execution_state", None),
            exchange_resolver=self._exchange_for_task,
            active_task_lookup=self.get_task,
            config_from_state=self._task_config_from_state,
            state_persister=self._persist_task_states,
            fund_releaser=self._release_task_funds,
            log=self.log,
        )

    async def close_task_state(self, id: int, user_id: int | None = None):
        return await self._stop_task_use_case().execute(id, user_id=user_id)

    async def stop_running_tasks_for_user(self, user_id: int) -> list[int]:
        task_repo = getattr(self.db_manager, "task", None)
        if task_repo is None:
            return []
        stop_uc = self._stop_task_use_case()
        return await StopUserRunningTasks(
            task_repo,
            stop_uc,
            active_tasks_provider=lambda uid: [
                task.ts for task in self.tasks.values() if getattr(task.ts, "user_id", None) == uid
            ],
        ).execute(user_id=user_id)

    def _task_config_from_state(self, state: TaskState) -> TaskConfig | None:
        try:
            return TaskConfigCodec.from_persisted_state(state)
        except Exception as exc:
            self.log.error(f"task state config parse failed: task_id={getattr(state, 'id', None)} error={exc}")
            return None

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

    def _cancel_orders_use_case(self) -> CancelTaskOpenOrders:
        return CancelTaskOpenOrders(
            execution_state_store=getattr(self.db_manager, "execution_state", None),
            log=self.log,
        )

    def _cleanup_before_start_use_case(self) -> CleanupRunningTasksBeforeStart:
        return CleanupRunningTasksBeforeStart(
            execution_state_store=getattr(self.db_manager, "execution_state", None),
            log=self.log,
        )

    async def _cancel_startup_open_orders(self, taskcs: list[TaskConfig]) -> None:
        await self._cleanup_before_start_use_case().execute_batch(
            taskcs,
            list(self.tasks.values()),
            exchange_resolver=self._exchange_for_task,
        )

    async def _cancel_task_start_open_orders(
        self,
        cfg,
        exchange,
        *,
        reason: str,
        seen: set[tuple[int, str]] | None = None,
    ) -> None:
        await self._cleanup_before_start_use_case().execute(
            cfg,
            list(self.tasks.values()),
            default_exchange=exchange,
            reason=reason,
            seen=seen,
        )

    async def _cancel_open_orders_for_task(
        self,
        task_id,
        exchange,
        *,
        reason: str,
        fallback_symbols=None,
        seen: set[tuple[int, str]] | None = None,
    ) -> bool:
        return await self._cancel_orders_use_case().execute(
            task_id,
            exchange,
            reason=reason,
            fallback_symbols=fallback_symbols,
            seen=seen,
        )

    def _cancel_open_orders_for_symbols(
        self,
        symbols,
        exchange,
        *,
        reason: str,
        task_id=None,
        seen: set[tuple[int, str]] | None = None,
    ) -> None:
        self._cancel_orders_use_case().cancel_for_symbols(
            symbols,
            exchange,
            reason=reason,
            task_id=task_id,
            seen=seen,
        )

    def _symbol_from_value(self, value) -> Symbol | None:
        return symbol_from_value(value)

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
