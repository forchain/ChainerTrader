import importlib
import inspect
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from trader.adapters.inbound.http.exceptions import translate_domain_exception
from trader.adapters.outbound.binance.exchange import BinanceExchange
from trader.auth.context import current_user
from trader.auth.credentials import FernetSecretCipher, decrypt_secret, service_key_available
from trader.common import path as trader_path
from trader.core.exchange.domain import ExchangeConfig, parse_exchange_config
from trader.core.exchange.use_cases import PreflightUserExchange
from trader.core.task.use_cases.submission import (
    default_taskset_file_name as _default_taskset_file_name,
)
from trader.core.task.use_cases.submission import (
    enforce_current_user_ownership as _enforce_current_user_ownership,
)
from trader.core.task.use_cases.submission import (
    normalize_save_file_name as _core_normalize_save_file_name,
)
from trader.core.task.use_cases.submission import (
    normalize_task_config_path as _normalize_task_config_path,
)
from trader.core.task.use_cases.submission import (
    task_submission_source as _task_submission_source,
)
from trader.core.task.use_cases.submission import (
    validate_config_file_source as _core_validate_config_file_source,
)
from trader.rpc.task_state_payload import public_task_state_dict
from trader.task.task_config import parse_task_config
from trader.task.task_type import TaskType

router = APIRouter()


async def _resolve_user(request: Request):
    composition = getattr(request.app.state, "composition", None)
    resolver = getattr(composition, "current_user_resolver", None)
    if callable(resolver):
        res = resolver(request)
        return await res if inspect.isawaitable(res) else res
    return await current_user(request)


def _validate_config_file_source(cfg: str) -> None:
    _core_validate_config_file_source(cfg, trader_path.get_file_path)


def _normalize_save_file_name(raw: str) -> str:
    return _core_normalize_save_file_name(raw)


@router.post("")
async def add_tasks(request: Request):
    raw_bytes = await request.body()
    cfg = raw_bytes.decode("utf-8")
    user = await _resolve_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    rpc_app = request.app.state.app
    source = _task_submission_source(cfg)
    try:
        _validate_config_file_source(cfg)
        taskcs = parse_task_config(cfg) if cfg else []
        _enforce_current_user_ownership(taskcs, user.id)
        await _stop_running_tasks_for_user(request, user)
        await _preflight_user_live_tasks(request, user, taskcs)
        result = rpc_app.send_add_tasks_msg(cfg, user_id=user.id)
    except HTTPException as exc:
        _log_task_submission_failure(rpc_app, user.id, source, str(exc.detail))
        raise
    except json.JSONDecodeError as exc:
        detail = f"invalid task JSON or config path: {exc.msg}"
        _log_task_submission_failure(rpc_app, user.id, source, detail)
        raise HTTPException(status_code=400, detail=detail) from exc
    except ValueError as exc:
        detail = f"invalid task config: {exc}"
        _log_task_submission_failure(rpc_app, user.id, source, detail)
        raise HTTPException(status_code=400, detail=detail) from exc
    except Exception as exc:
        http_exc = translate_domain_exception(exc)
        _log_task_submission_failure(rpc_app, user.id, source, str(http_exc.detail))
        raise http_exc from exc
    if result.get("result") != "success":
        detail = result.get("error") or "task manager rejected the task config"
        _log_task_submission_failure(rpc_app, user.id, source, detail)
        raise HTTPException(status_code=400, detail=detail)
    _log_task_submission_success(rpc_app, user.id, source, len(result.get("tasks", [])))
    return result


@router.get("")
async def get_tasks(request: Request):
    user = await _resolve_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    user_id = user.id
    tss = await request.app.state.app.task_manager.get_all_task_state(user_id=user_id)
    ret = []
    for ts in tss:
        ret.append(public_task_state_dict(ts))
    return ret


@router.get("/config-template")
async def config_template(path: str, request: Request):
    user = await _resolve_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    try:
        normalized = _normalize_task_config_path(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    resolved = trader_path.get_file_path(normalized)
    try:
        content = Path(resolved).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task config file not found: {normalized}") from exc
    return {"path": normalized, "content": content}


@router.post("/config-template/save")
async def save_config_template(request: Request):
    user = await _resolve_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid JSON payload") from exc

    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or len(tasks) == 0:
        raise HTTPException(status_code=400, detail="tasks must be a non-empty JSON array")

    try:
        file_name = _normalize_save_file_name(payload.get("file_name") or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not file_name:
        file_name = _default_taskset_file_name(tasks)
    if not file_name.endswith(".json"):
        file_name = f"{file_name}.json"

    rel_path = f"configs/tasks/saved/{file_name}"
    abs_path = trader_path.get_file_path(rel_path)
    output = Path(abs_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise HTTPException(status_code=409, detail=f"task config file already exists: {rel_path}")

    text = json.dumps(tasks, ensure_ascii=False, indent=2)
    output.write_text(text + "\n", encoding="utf-8")
    return {"path": rel_path, "file_name": file_name}


@router.get("/strategy-param-presets")
async def strategy_param_presets(strategy: str, request: Request):
    user = await _resolve_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    strategy_name = str(strategy or "").strip()
    if not strategy_name:
        raise HTTPException(status_code=400, detail="strategy is required")
    return {"strategy": strategy_name, "params": _strategy_param_defaults(strategy_name)}


async def _preflight_user_live_tasks(request: Request, user, taskcs) -> None:
    if user is None or getattr(user, "is_admin", False):
        return
    if not any(taskc.ttype == TaskType.TRADER for taskc in taskcs):
        return
    cfg = getattr(request.app.state, "cfg", None)
    service_key = getattr(cfg, "secret_key", None)
    rpc_app = getattr(request.app.state, "app", None)
    db_manager = getattr(rpc_app, "db_manager", None)
    preflight = PreflightUserExchange(
        getattr(db_manager, "exchange_credential", None),
        cipher=FernetSecretCipher(service_key) if service_key_available(service_key) else None,
    )
    try:
        await preflight.execute(
            user.id,
            connectivity_check=lambda credential: _user_exchange_ping_ok(cfg, service_key, credential),
        )
    except Exception as exc:
        raise translate_domain_exception(exc) from exc


async def _stop_running_tasks_for_user(request: Request, user) -> None:
    if user is None:
        return
    rpc_app = getattr(request.app.state, "app", None)
    task_manager = getattr(rpc_app, "task_manager", None)
    if task_manager is None:
        return
    stop_for_user = getattr(task_manager, "stop_running_tasks_for_user", None)
    if callable(stop_for_user) and getattr(getattr(task_manager, "db_manager", None), "task", None) is not None:
        await stop_for_user(user.id)
        return
    # Single-user single-run policy: only stop current user's running tasks.
    task_states = await task_manager.get_all_task_state(user_id=user.id)
    running_ids = [
        int(getattr(ts, "id", 0) or 0)
        for ts in task_states
        if getattr(getattr(ts, "state", None), "name", None) == "RUNNING"
    ]
    running_ids = sorted({task_id for task_id in running_ids if task_id > 0})
    for task_id in running_ids:
        close_task_state = getattr(task_manager, "close_task_state", None)
        if callable(close_task_state):
            await close_task_state(task_id, user_id=user.id)
        else:
            task_manager.close_task(task_id, user_id=user.id)


async def _preflight_single_running_task_per_user(request: Request, user) -> None:
    # Backward-compatible alias for older imports/callers.
    await _stop_running_tasks_for_user(request, user)


def _strategy_param_defaults(strategy_name: str) -> dict:
    try:
        module = importlib.import_module(f"trader.adapters.outbound.backtrader.{strategy_name}")
    except Exception:
        return {}

    try:
        from trader.adapters.outbound.backtrader.base_strategy import BaseStrategy
    except Exception:
        BaseStrategy = None

    candidates = []
    for attr in dir(module):
        obj = getattr(module, attr, None)
        if not isinstance(obj, type):
            continue
        if BaseStrategy is not None:
            try:
                if not issubclass(obj, BaseStrategy) or obj is BaseStrategy:
                    continue
            except Exception:
                continue
        params = getattr(obj, "params", None)
        if params is not None:
            candidates.append((obj.__name__, params))

    if not candidates:
        return {}

    # Prefer class name matching module stem (case-insensitive), otherwise first candidate.
    selected = None
    lowered = strategy_name.lower()
    for class_name, params in candidates:
        if class_name.lower() == lowered:
            selected = params
            break
    if selected is None:
        selected = candidates[0][1]

    defaults = {}
    try:
        for item in selected:
            if not isinstance(item, tuple) or len(item) != 2:
                continue
            key, value = item
            key_text = str(key or "").strip()
            if not key_text:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                defaults[key_text] = value
    except Exception:
        return {}
    return defaults


def _rpc_logger(rpc_app):
    logger = getattr(rpc_app, "logger", None)
    if logger is not None and hasattr(logger, "error"):
        return logger
    log = getattr(rpc_app, "log", None)
    if callable(log):
        return log()
    return None


def _log_task_submission_failure(rpc_app, user_id: int, source: str, detail: str) -> None:
    logger = _rpc_logger(rpc_app)
    if logger is not None:
        logger.error(f"Task submission failed: user_id={user_id} source={source} detail={detail}")


def _log_task_submission_success(rpc_app, user_id: int, source: str, task_count: int) -> None:
    logger = _rpc_logger(rpc_app)
    if logger is not None and hasattr(logger, "info"):
        logger.info(f"Task submission accepted: user_id={user_id} source={source} task_count={task_count}")


def _build_exchange_config(cfg, api_key: str, api_secret: str) -> ExchangeConfig:
    raw_exchange_cfg = getattr(cfg, "exchange", "") if cfg is not None else ""
    base = parse_exchange_config(raw_exchange_cfg) if raw_exchange_cfg else ExchangeConfig()
    payload = base.model_dump()
    payload["api_key"] = api_key
    payload["api_secret"] = api_secret
    return ExchangeConfig(**payload)


def _user_exchange_ping_ok(cfg, service_key: str, credential) -> bool:
    try:
        exchange_cfg = _build_exchange_config(
            cfg,
            decrypt_secret(service_key, credential.encrypted_api_key),
            decrypt_secret(service_key, credential.encrypted_api_secret),
        )
        exchange = BinanceExchange(exchange_cfg)
        return bool(exchange.ping())
    except Exception:
        return False
