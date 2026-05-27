import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from trader.auth.context import current_user
from trader.auth.credentials import decrypt_secret, service_key_available
from trader.common import path as trader_path
from trader.exchange.binance.exchange import BinanceExchange
from trader.exchange.exchange_config import ExchangeConfig, parse_exchange_config
from trader.task.task_config import parse_task_config
from trader.task.task_type import TaskType

router = APIRouter()


@router.post("")
async def add_tasks(request: Request):
    raw_bytes = await request.body()
    cfg = raw_bytes.decode("utf-8")
    user = await current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    rpc_app = request.app.state.app
    source = _task_submission_source(cfg)
    try:
        _validate_config_file_source(cfg)
        taskcs = parse_task_config(cfg) if cfg else []
        _enforce_current_user_ownership(taskcs, user.id)
        await _preflight_single_running_task_per_user(request, user)
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
    if result.get("result") != "success":
        detail = result.get("error") or "task manager rejected the task config"
        _log_task_submission_failure(rpc_app, user.id, source, detail)
        raise HTTPException(status_code=400, detail=detail)
    _log_task_submission_success(rpc_app, user.id, source, len(result.get("tasks", [])))
    return result


@router.get("")
async def get_tasks(request: Request):
    user = await current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    user_id = user.id
    tss = await request.app.state.app.task_manager.get_all_task_state(user_id=user_id)
    ret = []
    for ts in tss:
        ret.append(ts.to_dict())
    return ret


@router.get("/config-template")
async def config_template(path: str, request: Request):
    user = await current_user(request)
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


async def _preflight_user_live_tasks(request: Request, user, taskcs) -> None:
    if user is None or getattr(user, "is_admin", False):
        return
    if not any(taskc.ttype == TaskType.TRADER for taskc in taskcs):
        return
    cfg = getattr(request.app.state, "cfg", None)
    if not service_key_available(getattr(cfg, "secret_key", None)):
        raise HTTPException(status_code=400, detail="TRADER_SECRET_KEY is required to start user-owned live trading tasks")
    rpc_app = getattr(request.app.state, "app", None)
    db_manager = getattr(rpc_app, "db_manager", None)
    credential_repo = getattr(db_manager, "exchange_credential", None)
    if credential_repo is None:
        raise HTTPException(status_code=400, detail="live trading requires a user exchange credential store")
    credential = await credential_repo.get_default(user.id, "BINANCE")
    if credential is None:
        raise HTTPException(status_code=400, detail=f"missing BINANCE API credential for user_id={user.id}")
    service_key = getattr(cfg, "secret_key", None)
    if not _user_exchange_ping_ok(cfg, service_key, credential):
        raise HTTPException(status_code=400, detail=f"invalid BINANCE API credential or connectivity failure for user_id={user.id}")


async def _preflight_single_running_task_per_user(request: Request, user) -> None:
    if user is None:
        return
    rpc_app = getattr(request.app.state, "app", None)
    task_manager = getattr(rpc_app, "task_manager", None)
    if task_manager is None:
        return
    task_states = await task_manager.get_all_task_state(user_id=user.id)
    if any(getattr(getattr(ts, "state", None), "name", None) == "RUNNING" for ts in task_states):
        raise HTTPException(status_code=409, detail=f"user_id={user.id} already has a running task")


def _task_submission_source(cfg: str) -> str:
    text = (cfg or "").strip()
    if text.startswith("[") or text.startswith("{"):
        return "inline-json"
    if not text:
        return "empty"
    normalized = " ".join(text.split())
    if len(normalized) > 240:
        return f"{normalized[:240]}..."
    return normalized


def _validate_config_file_source(cfg: str) -> None:
    text = (cfg or "").strip()
    if not text or text.startswith("[") or text.startswith("{"):
        return
    if not text.endswith(".json"):
        return
    normalized = _normalize_task_config_path(text)
    if os.path.isfile(trader_path.get_file_path(normalized)):
        return
    raise ValueError(f"task config file not found: {normalized}")


def _normalize_task_config_path(raw_path: str) -> str:
    text = (raw_path or "").strip().replace("\\", "/")
    if not text:
        raise ValueError("task config path is required")
    if text.startswith("/") or text.startswith("./") or "/../" in f"/{text}/" or text.startswith("../"):
        raise ValueError(f"invalid task config path: {raw_path}")
    if not text.startswith("configs/tasks/"):
        raise ValueError(f"task config path must be under configs/tasks: {raw_path}")
    if not text.endswith(".json"):
        raise ValueError(f"task config path must end with .json: {raw_path}")
    return text


def _rpc_logger(rpc_app):
    logger = getattr(rpc_app, "logger", None)
    if logger is not None and hasattr(logger, "error"):
        return logger
    log = getattr(rpc_app, "log", None)
    if callable(log):
        return log()
    return None


def _enforce_current_user_ownership(taskcs, current_user_id: int) -> None:
    for taskc in taskcs or []:
        taskc.user_id = current_user_id


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
