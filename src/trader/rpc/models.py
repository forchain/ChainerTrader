import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from trader.core.exchange.domain import Balance
from trader.core.exchange.interfaces import ExchangeClient
from trader.core.exchange.use_cases import BuildAccountView, SymbolOpenOrders
from trader.core.shared.domain import Symbol
from trader.core.task.domain import TaskStateType
from trader.core.task.use_cases import ListTasks, TaskScope, paginate
from trader.rpc.task_state_payload import public_task_state_dict

if TYPE_CHECKING:
    from trader.app.app import App


class TasksInfo(BaseModel):
    total: int = 0
    completed: int = 0
    tasks: list[dict[str, Any]]
    page: int = 1
    per_page: int = 0
    total_pages: int = 1


class AcctsInfo(BaseModel):
    total: int = 0
    balances: list[Balance]
    open_orders: list[dict[str, Any]] = Field(default_factory=list)
    locked_reasons: list[dict[str, Any]] = Field(default_factory=list)
    borrow_asset: str = ""
    borrowable_amount: float = 0
    operable_amount: float = 0
    account_error: str = ""


class LogsInfo(BaseModel):
    total: int = 0
    logs: list[str]


class KlinesInfo(BaseModel):
    total: int = 0
    name: str
    klines: list[dict[str, Any]]


async def get_taskinfo(app: "App", user=None, page: int = 1, per_page: int | None = None) -> TasksInfo:
    user_id = None if user is None else user.id
    scope = TaskScope.all() if user_id is None else TaskScope.for_user(user_id)
    states = await ListTasks(app.task_manager).execute(scope)
    completed = 0
    tasks: list[dict[str, Any]] = []
    for ts in states.items:
        if ts.state == TaskStateType.DONE:
            completed += 1
        item = public_task_state_dict(ts)
        try:
            payload = json.loads(item.get("config_json") or "[]")
            cfg = payload[0] if isinstance(payload, list) and payload and isinstance(payload[0], dict) else {}
        except Exception:
            cfg = {}
        run_id = str(cfg.get("run_id") or "").strip() or str(cfg.get("task_batch_id") or "").strip() or None
        item["run_id"] = run_id
        item["symbol"] = str(cfg.get("symbol") or "").strip()
        item["interval"] = str(cfg.get("interval") or "").strip()
        item["strategy"] = str(cfg.get("strategy") or cfg.get("strategies") or "").strip()
        tasks.append(item)

    # Assign ordinal labels for grouped runs.
    run_groups: dict[str, list[dict[str, Any]]] = {}
    for item in tasks:
        run_id = item.get("run_id")
        if not run_id:
            continue
        run_groups.setdefault(str(run_id), []).append(item)
    for _run_id, items in run_groups.items():
        ordered = sorted(items, key=lambda x: int(x.get("task_id") or 0))
        total = len(ordered)
        for idx, item in enumerate(ordered, start=1):
            item["run_index"] = idx
            item["run_total"] = total

    # Sort tasks by start_time in descending order (newest first)
    tasks.sort(key=lambda x: x.get("start_time", ""), reverse=True)

    result = paginate(tasks, page=page, per_page=per_page)
    return TasksInfo(
        total=result.total,
        completed=completed,
        tasks=result.items,
        page=result.page,
        per_page=result.per_page,
        total_pages=result.total_pages,
    )


def get_accounts_info(app: "App", *, include_open_orders: bool = True) -> AcctsInfo:
    view = BuildAccountView(
        app.exchange,
        symbol_interval=getattr(getattr(app, "task_manager", None), "latest_si", None),
        logger=getattr(app, "logger", None),
    ).execute(include_open_orders=include_open_orders)
    return AcctsInfo(
        total=len(view.balances),
        balances=view.balances,
        open_orders=[order.as_dict() for order in view.open_orders],
        locked_reasons=[order.as_dict() for order in view.locked_source],
        borrow_asset=view.borrow_asset,
        borrowable_amount=view.borrowable_amount,
        operable_amount=view.operable_amount,
        account_error=view.account_error,
    )


def open_orders_for_symbol_from_exchange(exchange: ExchangeClient, symbol: Symbol) -> list[dict[str, Any]]:
    return [order.as_dict() for order in SymbolOpenOrders(exchange).list(symbol)]


def get_logs_info(app: "App") -> LogsInfo:
    logs = app.logger.get_buffer_str()

    return LogsInfo(total=len(logs), logs=logs)


async def get_klines_info(app: "App") -> KlinesInfo:
    if not app.task_manager.latest_si:
        return KlinesInfo(total=0, klines=[], name="")

    kls_cache = await app.db_manager.kline.get_latest_klines(app.task_manager.latest_si.name(), 1000)

    klines: list[dict[str, Any]] = []
    if len(kls_cache) > 0:
        for kl in kls_cache:
            klines.append(kl.to_dict())

    return KlinesInfo(total=0, klines=klines, name=f"{app.task_manager.latest_si.name()}")
