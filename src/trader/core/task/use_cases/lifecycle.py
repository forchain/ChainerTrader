"""Task lifecycle orchestration use cases: submit, stop, and single-running-task-per-user policy."""

from __future__ import annotations

import inspect
from datetime import datetime
from typing import Any, Callable

from trader.core.task.domain import TaskState, TaskStateType, task_state_name
from trader.core.task.interfaces import FundReservationStore, TaskRepository, TaskRunner
from trader.core.task.use_cases.cleanup import CancelTaskOpenOrders
from trader.core.task.use_cases.fund_reservation import PreflightLiveTaskFunds, ReleaseTaskFunds
from trader.core.task.use_cases.recovery import parse_persisted_task_config


def _default_config_from_state(state: TaskState) -> Any:
    config_json = str(getattr(state, "config_json", "") or "").strip()
    if not config_json:
        return None
    try:
        parsed = parse_persisted_task_config(config_json)
    except Exception:
        return None
    for cfg in parsed:
        if int(getattr(cfg, "id", 0) or 0) == int(getattr(state, "id", 0) or 0):
            return cfg
    return parsed[0] if parsed else None


class StopTask:
    """Stop an active or persisted running task, clean up task-scoped open orders, and release funds."""

    def __init__(
        self,
        *,
        task_repository: TaskRepository | None,
        fund_reservation_store: FundReservationStore | None = None,
        execution_state_store: Any = None,
        exchange_resolver: Callable[[Any], Any] | None = None,
        active_task_lookup: Callable[[int], Any] | None = None,
        config_from_state: Callable[[TaskState], Any] | None = None,
        state_persister: Callable[[list[TaskState]], Any] | None = None,
        fund_releaser: Callable[..., Any] | None = None,
        log: Any = None,
    ):
        self.task_repository = task_repository
        self.release_funds = ReleaseTaskFunds(fund_reservation_store, log=log)
        self.cancel_orders = CancelTaskOpenOrders(execution_state_store=execution_state_store, log=log)
        self.exchange_resolver = exchange_resolver
        self.active_task_lookup = active_task_lookup
        self.config_from_state = config_from_state or _default_config_from_state
        self.state_persister = state_persister
        self.fund_releaser = fund_releaser

    async def _persist_states(self, states: list[TaskState]) -> None:
        if not states:
            return
        if self.state_persister is not None:
            res = self.state_persister(states)
            if inspect.isawaitable(res):
                await res
            return
        if self.task_repository is not None:
            await self.task_repository.add_tasks(states)

    async def _release_task_funds(self, task_id: int, *, reason: str) -> None:
        if self.fund_releaser is not None:
            res = self.fund_releaser(task_id, reason=reason)
            if inspect.isawaitable(res):
                await res
            return
        await self.release_funds.execute(task_id, reason=reason)

    async def execute(self, task_id: int, *, user_id: int | None = None) -> bool:
        active = self.active_task_lookup(task_id) if self.active_task_lookup is not None else None
        if active is not None:
            if user_id is not None and getattr(active.ts, "user_id", None) != user_id:
                return False
            active.stop()
            si = getattr(active.tcfg, "symbol_interval", None)
            await self.cancel_orders.execute(
                getattr(active.tcfg, "id", task_id),
                getattr(active, "exchange", None),
                reason="task_closed",
                fallback_symbols=[si.sy] if si is not None else [],
            )
            await self._persist_states([active.ts])
            await self._release_task_funds(task_id, reason="task_closed")
            return True

        if self.task_repository is None:
            return False
        if user_id is not None:
            state = await self.task_repository.get_task_for_user(task_id, user_id)
        else:
            state = await self.task_repository.get_task(task_id)
        if state is None or not state.is_running():
            return False

        cfg = self.config_from_state(state) if self.config_from_state is not None else None
        if cfg is not None and self.exchange_resolver is not None:
            task_exchange = self.exchange_resolver(cfg)
            if inspect.isawaitable(task_exchange):
                task_exchange = await task_exchange
            si = getattr(cfg, "symbol_interval", None)
            await self.cancel_orders.execute(
                task_id,
                task_exchange,
                reason="task_closed",
                fallback_symbols=[si.sy] if si is not None else [],
            )

        state.state = TaskStateType.DONE
        await self._persist_states([state])
        await self._release_task_funds(task_id, reason="task_closed")
        return True


class StopUserRunningTasks:
    """Enforce single-running-task-per-user policy by stopping only the requesting user's running tasks."""

    def __init__(
        self,
        task_repository: TaskRepository,
        stop_task: StopTask,
        *,
        active_tasks_provider: Callable[[int], list[TaskState]] | None = None,
    ):
        self.task_repository = task_repository
        self.stop_task = stop_task
        self.active_tasks_provider = active_tasks_provider

    async def execute(self, *, user_id: int) -> list[int]:
        states: list[TaskState] = []
        if self.active_tasks_provider is not None:
            states.extend(self.active_tasks_provider(user_id))
        persisted = await self.task_repository.get_all_tasks_for_user(user_id)
        states.extend(persisted)

        running_ids = sorted(
            {
                int(getattr(ts, "id", 0) or 0)
                for ts in states
                if getattr(getattr(ts, "state", None), "name", None) == "RUNNING" and int(getattr(ts, "id", 0) or 0) > 0
            }
        )
        stopped: list[int] = []
        for task_id in running_ids:
            if await self.stop_task.execute(task_id, user_id=user_id):
                stopped.append(task_id)
        return stopped


class SubmitTasks:
    """Orchestrate task batch submission: fund preflight, execution, terminal state persistence, and fund release."""

    def __init__(
        self,
        *,
        task_repository: TaskRepository | None,
        task_runner: TaskRunner,
        preflight_funds: PreflightLiveTaskFunds | None = None,
        release_funds: ReleaseTaskFunds | None = None,
        commission: float = 0.0,
        default_cash: float = 0.0,
    ):
        self.task_repository = task_repository
        self.task_runner = task_runner
        self.preflight_funds = preflight_funds
        self.release_funds = release_funds
        self.commission = float(commission)
        self.default_cash = float(default_cash)

    async def execute(self, taskcs: list[Any], **runner_kwargs: Any) -> list[TaskState]:
        if not taskcs:
            return []
        try:
            if self.preflight_funds is not None:
                await self.preflight_funds.execute(taskcs)

            completed_states: list[TaskState] = []
            for cfg in taskcs:
                state = await self.task_runner.run(cfg, **runner_kwargs)
                if state is not None:
                    state.state = TaskStateType.DONE
                    completed_states.append(state)

            if self.task_repository is not None and completed_states:
                await self.task_repository.add_tasks(completed_states)
            if self.release_funds is not None:
                for cfg in taskcs:
                    await self.release_funds.execute(int(cfg.id), reason="task_done")
            return completed_states
        except Exception as exc:
            persist_exc = None
            try:
                if self.task_repository is not None:
                    failed_states = []
                    for cfg in taskcs:
                        failed_state = TaskState(
                            int(cfg.id),
                            task_state_name(cfg),
                            datetime.now(),
                            commission=self.commission,
                            strategy_start_time=getattr(cfg, "start_time", 0),
                            strategy_end_time=getattr(cfg, "end_time", 0),
                            initial_cash=getattr(cfg, "free", 0) if getattr(cfg, "free", -1) >= 0 else self.default_cash,
                            user_id=getattr(cfg, "user_id", None),
                            error_message=str(exc),
                        )
                        failed_state.state = TaskStateType.FAILED
                        failed_states.append(failed_state)
                    await self.task_repository.add_tasks(failed_states)
            except Exception as failed_exc:
                persist_exc = failed_exc
            if self.release_funds is not None:
                for cfg in taskcs:
                    await self.release_funds.execute(int(cfg.id), reason="task_failed")
            if persist_exc is not None:
                raise persist_exc
            raise
