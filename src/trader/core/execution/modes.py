"""Live execution mode and margin-borrow policy values shared by the core layers.

These values live in ``trader.core`` so task configuration, execution routing,
and the live adapters can all agree on them without importing each other.
"""

from __future__ import annotations

from enum import Enum


class LiveExecutionMode(str, Enum):
    MANUAL_NOTIFY = "manual_notify"
    AUTO_TRADE = "auto_trade"


class MarginBorrowBlockPolicy(str, Enum):
    SKIP_CONTINUE = "skip_continue"
    REPAY_SINGLE = "repay_single"
    REPAY_ALL = "repay_all"
    STOP_TASK = "stop_task"


MANUAL_NOTIFY_MODE = LiveExecutionMode.MANUAL_NOTIFY.value
AUTO_TRADE_MODE = LiveExecutionMode.AUTO_TRADE.value

SUPPORTED_LIVE_EXECUTION_MODES = {LiveExecutionMode.MANUAL_NOTIFY.value, LiveExecutionMode.AUTO_TRADE.value}
REAL_AUTO_MODES = {LiveExecutionMode.AUTO_TRADE.value}
SUPPORTED_MARGIN_BORROW_BLOCK_POLICIES = {
    MarginBorrowBlockPolicy.SKIP_CONTINUE.value,
    MarginBorrowBlockPolicy.REPAY_SINGLE.value,
    MarginBorrowBlockPolicy.REPAY_ALL.value,
    MarginBorrowBlockPolicy.STOP_TASK.value,
}


def normalize_live_execution_mode(value: str | LiveExecutionMode | None) -> str:
    raw = value.value if isinstance(value, LiveExecutionMode) else value
    mode = str(raw or LiveExecutionMode.AUTO_TRADE.value).strip().lower()
    if mode not in SUPPORTED_LIVE_EXECUTION_MODES:
        raise ValueError(f"unsupported live_execution_mode: {raw}")
    return mode


def normalize_margin_borrow_block_policy(value: str | MarginBorrowBlockPolicy | None) -> str:
    raw = value.value if isinstance(value, MarginBorrowBlockPolicy) else value
    mode = str(raw or MarginBorrowBlockPolicy.SKIP_CONTINUE.value).strip().lower()
    aliases = {
        "skip": MarginBorrowBlockPolicy.SKIP_CONTINUE.value,
        "skip_short_continue": MarginBorrowBlockPolicy.SKIP_CONTINUE.value,
        "skip_continue": MarginBorrowBlockPolicy.SKIP_CONTINUE.value,
        "auto_repay_then_retry_once": MarginBorrowBlockPolicy.REPAY_SINGLE.value,
        "repay_symbol_assets_retry": MarginBorrowBlockPolicy.REPAY_SINGLE.value,
        "repay_single": MarginBorrowBlockPolicy.REPAY_SINGLE.value,
        "repay_all_liabilities_retry": MarginBorrowBlockPolicy.REPAY_ALL.value,
        "repay_all": MarginBorrowBlockPolicy.REPAY_ALL.value,
        "hard_fail_stop_task": MarginBorrowBlockPolicy.STOP_TASK.value,
        "stop_task": MarginBorrowBlockPolicy.STOP_TASK.value,
    }
    mode = aliases.get(mode, mode)
    if mode not in SUPPORTED_MARGIN_BORROW_BLOCK_POLICIES:
        raise ValueError(f"unsupported live_margin_borrow_block_policy: {raw}")
    return mode


def is_manual_notify_mode(value: str | None) -> bool:
    return normalize_live_execution_mode(value) == LiveExecutionMode.MANUAL_NOTIFY.value


def is_real_auto_mode(value: str | None) -> bool:
    return normalize_live_execution_mode(value) in REAL_AUTO_MODES
