"""Task submission validation, ownership enforcement, and saved-config naming rules."""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable


def enforce_current_user_ownership(taskcs: Iterable, current_user_id: int) -> None:
    """Stamp every submitted TaskConfig with the authenticated user's id."""
    for taskc in taskcs or []:
        taskc.user_id = current_user_id


def task_submission_source(cfg: str) -> str:
    text = (cfg or "").strip()
    if text.startswith("[") or text.startswith("{"):
        return "inline-json"
    if not text:
        return "empty"
    normalized = " ".join(text.split())
    if len(normalized) > 240:
        return f"{normalized[:240]}..."
    return normalized


def normalize_task_config_path(raw_path: str) -> str:
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


def validate_config_file_source(cfg: str, path_resolver) -> None:
    text = (cfg or "").strip()
    if not text or text.startswith("[") or text.startswith("{"):
        return
    if not text.endswith(".json"):
        return
    normalized = normalize_task_config_path(text)
    if os.path.isfile(path_resolver(normalized)):
        return
    raise ValueError(f"task config file not found: {normalized}")


def _slug(text: str) -> str:
    lowered = str(text or "").strip().lower()
    lowered = lowered.replace("/", "-").replace(" ", "-")
    lowered = re.sub(r"[^a-z0-9_-]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered).strip("-_")
    return lowered


def normalize_save_file_name(raw: str) -> str:
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        return ""
    if "/" in text:
        raise ValueError("file_name must not contain path separators")
    if text in {".", ".."}:
        raise ValueError("invalid file_name")
    stem = text[:-5] if text.lower().endswith(".json") else text
    stem = _slug(stem)
    if not stem:
        raise ValueError("invalid file_name")
    return f"{stem}.json"


def default_taskset_file_name(tasks: list[dict]) -> str:
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
