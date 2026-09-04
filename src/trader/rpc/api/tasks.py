import json
import os
import re
import importlib
from pathlib import Path
from datetime import datetime

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


@router.post("/config-template/save")
async def save_config_template(request: Request):
    user = await current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid JSON payload") from exc

    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or len(tasks) == 0:
        raise HTTPException(status_code=400, detail="tasks must be a non-empty JSON array")

    file_name = _normalize_save_file_name(payload.get("file_name") or "")
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
    user = await current_user(request)
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


async def _stop_running_tasks_for_user(request: Request, user) -> None:
    if user is None:
        return
    rpc_app = getattr(request.app.state, "app", None)
    task_manager = getattr(rpc_app, "task_manager", None)
    if task_manager is None:
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
        task_manager.close_task(task_id, user_id=user.id)


async def _preflight_single_running_task_per_user(request: Request, user) -> None:
    # Backward-compatible alias for older imports/callers.
    await _stop_running_tasks_for_user(request, user)


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


def _slug(text: str) -> str:
    lowered = str(text or "").strip().lower()
    lowered = lowered.replace("/", "-").replace(" ", "-")
    lowered = re.sub(r"[^a-z0-9_-]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered).strip("-_")
    return lowered


def _normalize_save_file_name(raw: str) -> str:
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        return ""
    if "/" in text:
        raise HTTPException(status_code=400, detail="file_name must not contain path separators")
    if text in {".", ".."}:
        raise HTTPException(status_code=400, detail="invalid file_name")
    stem = text[:-5] if text.lower().endswith(".json") else text
    stem = _slug(stem)
    if not stem:
        raise HTTPException(status_code=400, detail="invalid file_name")
    return f"{stem}.json"


def _default_taskset_file_name(tasks: list[dict]) -> str:
    items = [item for item in tasks if isinstance(item, dict)]
    count = max(1, len(items))

    def _uniq(field_getter):
        values = []
        for item in items:
            value = _slug(field_getter(item))
            if value:
                values.append(value)
        uniq_values = sorted(set(values))
        if not uniq_values:
            return "mixed"
        if len(uniq_values) == 1:
            return uniq_values[0]
        return f"mixed{len(uniq_values)}"

    task_type = _uniq(lambda item: str(item.get("task_type") or ""))
    interval = _uniq(lambda item: str(item.get("interval") or ""))
    strategy = _uniq(lambda item: str(item.get("strategy") or item.get("strategies") or ""))
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{task_type}_{interval}_{strategy}_n{count}_{timestamp}.json"


def _strategy_param_defaults(strategy_name: str) -> dict:
    try:
        module = importlib.import_module(f"trader.strategy.{strategy_name}")
    except Exception:
        return {}

    try:
        from trader.strategy.base_strategy import BaseStrategy
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
