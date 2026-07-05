import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from trader.exchange.balance import Balance
from trader.rpc.task_state_payload import public_task_state_dict
from trader.utils.symbol_interval import Symbol
from trader.utils.task_state import TaskStateType

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
    tss = await app.task_manager.get_all_task_state(user_id=user_id)
    completed = 0
    tasks: list[dict[str, Any]] = []
    for ts in tss:
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

    total = len(tss)
    safe_page = max(1, int(page))
    if per_page is None:
        return TasksInfo(total=total, completed=completed, tasks=tasks, page=1, per_page=total, total_pages=1)
    safe_per_page = max(1, int(per_page))
    total_pages = max(1, (total + safe_per_page - 1) // safe_per_page)
    safe_page = min(safe_page, total_pages)
    start = (safe_page - 1) * safe_per_page
    end = start + safe_per_page
    return TasksInfo(
        total=total,
        completed=completed,
        tasks=tasks[start:end],
        page=safe_page,
        per_page=safe_per_page,
        total_pages=total_pages,
    )


def get_accounts_info(app: "App", *, include_open_orders: bool = True) -> AcctsInfo:
    if app.exchange is None:
        return AcctsInfo(total=0, balances=[])
    errors: list[str] = []
    try:
        balances = list(app.exchange.get_account_balances())
    except Exception as exc:
        message = f"交易所账户读取失败: {exc}"
        _log_account_info_error(app, "exchange balance", exc)
        return AcctsInfo(total=0, balances=[], account_error=message)
    borrow_asset = _borrow_asset_from_exchange(app.exchange, balances, getattr(getattr(app, "task_manager", None), "latest_si", None))
    try:
        borrowable_amount = _get_max_borrowable_amount(app.exchange, borrow_asset)
    except Exception as exc:
        borrowable_amount = 0.0
        errors.append(f"最大可借额度读取失败: {exc}")
        _log_account_info_error(app, "max borrowable", exc)
    open_orders = []
    if include_open_orders:
        try:
            open_orders = _open_orders_from_exchange(
                app.exchange,
                balances,
                getattr(getattr(app, "task_manager", None), "latest_si", None),
                borrow_asset,
            )
        except Exception as exc:
            errors.append(f"开放订单读取失败: {exc}")
            _log_account_info_error(app, "locked orders", exc)
    locked_reasons = list(open_orders)
    operable_amount = _operable_amount(balances, borrow_asset, borrowable_amount)
    for balance in balances:
        if balance.asset == borrow_asset:
            balance.max_borrowable = borrowable_amount
            balance.operable = operable_amount
            break

    return AcctsInfo(
        total=len(balances),
        balances=balances,
        open_orders=open_orders,
        locked_reasons=locked_reasons,
        borrow_asset=borrow_asset,
        borrowable_amount=borrowable_amount,
        operable_amount=operable_amount,
        account_error="；".join(errors),
    )


def _log_account_info_error(app: "App", operation: str, exc: Exception) -> None:
    logger = getattr(app, "logger", None)
    if logger is not None and hasattr(logger, "error"):
        logger.error(f"account page {operation} read failed: {exc}")


def _borrow_asset_from_exchange(exchange: Any, balances: list[Balance], symbol: Any = None) -> str:
    if symbol is not None:
        quote = getattr(getattr(symbol, "sy", None), "quote", None)
        if quote:
            return str(quote).upper()
    margin_mode = getattr(exchange, "margin_mode", None)
    if margin_mode is not None and getattr(margin_mode, "value", "") != "spot":
        return str(getattr(exchange, "borrow_asset", None) or "USDT").upper()
    if balances:
        for balance in balances:
            if balance.asset == "USDT":
                return "USDT"
        return balances[0].asset
    return "USDT"


def _get_max_borrowable_amount(exchange: Any, asset: str) -> float:
    reader = getattr(exchange, "get_max_borrowable", None)
    if not callable(reader):
        return 0.0
    payload = reader(asset)
    if isinstance(payload, dict):
        return float(payload.get("amount", 0.0) or 0.0)
    return float(getattr(payload, "amount", 0.0) or 0.0)


def _open_orders_from_exchange(exchange: Any, balances: list[Balance], symbol: Any = None, quote_asset: str | None = None) -> list[dict[str, Any]]:
    reader = getattr(exchange, "get_open_orders", None)
    if not callable(reader):
        return []
    quote = _quote_asset_for_locked_symbol_search(symbol, quote_asset)
    all_reader = getattr(exchange, "get_all_open_orders", None)
    if quote and quote in _locked_balance_assets(balances) and callable(all_reader):
        try:
            rows = all_reader() or []
        except Exception:
            rows = []
        if rows:
            return _open_order_rows(rows)
    rows: list[Any] = []
    for order_symbol in open_order_symbols_from_locked_balances(balances, symbol=symbol, quote_asset=quote):
        rows.extend(reader(order_symbol) or [])
    return _open_order_rows(rows)


def open_orders_for_symbol_from_exchange(exchange: Any, symbol: Symbol) -> list[dict[str, Any]]:
    reader = getattr(exchange, "get_open_orders", None)
    if not callable(reader):
        return []
    return _open_order_rows(reader(symbol) or [])


def open_order_symbols_from_locked_balances(
    balances: list[Balance],
    *,
    symbol: Any = None,
    quote_asset: str | None = None,
) -> list[Symbol]:
    locked_assets = _locked_balance_assets(balances)
    if not locked_assets:
        return []
    quote = _quote_asset_for_locked_symbol_search(symbol, quote_asset)
    if not quote:
        return []

    ret: list[Symbol] = []
    seen: set[str] = set()

    current_symbol = _symbol_from_symbol_interval(symbol)
    if current_symbol is not None and {current_symbol.base, current_symbol.quote} & set(locked_assets):
        _append_symbol_once(ret, seen, current_symbol)

    for asset in locked_assets:
        if asset == quote:
            continue
        _append_symbol_once(ret, seen, Symbol(f"{asset}-{quote}"))
    return ret


def _locked_balance_assets(balances: list[Balance]) -> list[str]:
    ret: list[str] = []
    seen: set[str] = set()
    for balance in balances:
        try:
            locked = float(balance.locked or 0.0)
        except (TypeError, ValueError):
            continue
        asset = str(balance.asset or "").strip().upper()
        if locked <= 0 or not asset or asset in seen:
            continue
        seen.add(asset)
        ret.append(asset)
    return ret


def _quote_asset_for_locked_symbol_search(symbol: Any = None, quote_asset: str | None = None) -> str:
    current_symbol = _symbol_from_symbol_interval(symbol)
    if current_symbol is not None and current_symbol.quote:
        return current_symbol.quote
    return str(quote_asset or "USDT").strip().upper()


def _symbol_from_symbol_interval(symbol: Any = None) -> Symbol | None:
    if symbol is None:
        return None
    if isinstance(symbol, Symbol):
        return symbol
    if hasattr(symbol, "sy"):
        base = str(getattr(symbol.sy, "base", "") or "").strip().upper()
        quote = str(getattr(symbol.sy, "quote", "") or "").strip().upper()
        if base and quote:
            return Symbol(f"{base}-{quote}")
    return None


def _append_symbol_once(ret: list[Symbol], seen: set[str], symbol: Symbol) -> None:
    name = symbol.name()
    if not name or name in seen:
        return
    seen.add(name)
    ret.append(symbol)


def _open_order_rows(rows: Any) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        info = row.get("info") if isinstance(row.get("info"), dict) else {}
        symbol = str(row.get("symbol") or info.get("symbol") or "")
        symbol = symbol.replace("/", "")
        order_id = row.get("orderId") or row.get("order_id") or row.get("id") or info.get("orderId") or info.get("order_id")
        reasons.append(
            {
                "symbol": symbol,
                "side": str(row.get("side") or info.get("side") or ""),
                "quantity": float(row.get("origQty") or row.get("amount") or row.get("quantity") or 0.0),
                "order_id": str(order_id or ""),
                "order_type": str(row.get("type") or info.get("type") or ""),
                "price": float(row.get("price") or 0.0),
                "status": str(row.get("status") or info.get("status") or ""),
            }
        )
    return reasons


def _operable_amount(balances: list[Balance], borrow_asset: str, borrowable_amount: float) -> float:
    free_balance = 0.0
    for balance in balances:
        if balance.asset == borrow_asset:
            free_balance = float(balance.free or 0.0)
            break
    return free_balance + float(borrowable_amount or 0.0)


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
