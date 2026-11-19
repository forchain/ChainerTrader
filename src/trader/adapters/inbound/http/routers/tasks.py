import inspect
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from trader.adapters.inbound.http.exceptions import translate_domain_exception
from trader.adapters.inbound.http.presenters import public_task_state_dict
from trader.auth.context import current_user
from trader.common import path as trader_path
from trader.core.exchange.account_lifecycle import LiveAccountLifecycle
from trader.core.exchange.domain import MarginMode
from trader.core.exchange.use_cases import PreflightUserExchange, base_exchange_config
from trader.core.task.config_codec import TaskConfigCodec
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
from trader.task.task_config import read_task_config_source
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
    _core_validate_config_file_source(cfg, lambda path: os.path.isfile(trader_path.get_file_path(path)))


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
        taskcs = (
            TaskConfigCodec.from_input(
                read_task_config_source(cfg), min_live_trade_notional=getattr(request.app.state.cfg, "min_live_trade_notional", 11.0)
            )
            if cfg
            else []
        )
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
    return {"strategy": strategy_name, "params": _strategy_param_defaults(request, strategy_name)}


async def _preflight_user_live_tasks(request: Request, user, taskcs) -> None:
    if user is None or getattr(user, "is_admin", False):
        return
    if not any(taskc.ttype == TaskType.TRADER for taskc in taskcs):
        return
    cfg = getattr(request.app.state, "cfg", None)
    composition = getattr(request.app.state, "composition", None)
    rpc_app = getattr(request.app.state, "app", None)
    db_manager = getattr(rpc_app, "db_manager", None)
    cipher = _secret_cipher(composition, cfg)
    validator = getattr(composition, "credential_connectivity_validator", None)
    preflight = PreflightUserExchange(getattr(db_manager, "exchange_credential", None), cipher=cipher)
    try:
        if callable(validator):

            def connectivity_check(credential):
                return _validator_ping_ok(cfg, cipher, validator, credential)

        else:
            exchange_factory = _exchange_factory(composition)

            def connectivity_check(credential):
                return _user_exchange_ping_ok(cfg, cipher, exchange_factory, credential)

        await preflight.execute(user.id, connectivity_check=connectivity_check)
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


def _strategy_param_defaults(request: Request, strategy_name: str) -> dict:
    provider = getattr(getattr(request.app.state, "composition", None), "strategy_param_defaults", None)
    return dict(provider(strategy_name)) if callable(provider) else {}


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


def _secret_cipher(composition, cfg):
    factory = getattr(composition, "secret_cipher_factory", None)
    return factory(getattr(cfg, "secret_key", None)) if callable(factory) else None


def _exchange_factory(composition):
    factory = getattr(composition, "user_exchange_factory", None)
    return factory if callable(factory) else None


def _validator_ping_ok(cfg, cipher, validator, credential) -> bool:
    try:
        context = LiveAccountLifecycle.build_credential_context(
            base_cfg=base_exchange_config(None, cfg),
            cipher=cipher,
            credential=credential,
            user_id=0,
            margin_mode=MarginMode.SPOT,
        )
    except Exception:
        return False
    return validator(context.cfg, "BINANCE", context.cfg.api_key, context.cfg.api_secret) is None


def _user_exchange_ping_ok(cfg, cipher, exchange_factory, credential) -> bool:
    if exchange_factory is None:
        return False
    try:
        context = LiveAccountLifecycle.build_credential_context(
            base_cfg=base_exchange_config(None, cfg),
            cipher=cipher,
            credential=credential,
            user_id=0,
            margin_mode=MarginMode.SPOT,
        )
        return bool(exchange_factory(context.cfg).ping())
    except Exception:
        return False
