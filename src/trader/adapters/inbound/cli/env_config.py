"""Environment and CLI configuration loading for the inbound CLI adapter."""

from __future__ import annotations

import os
from argparse import Namespace
from typing import Any

from trader.core.shared.config import (
    DEFAULT_PERIOD,
    TRADER_API,
    TRADER_AUTH_PASSWORD,
    TRADER_AUTH_USERNAME,
    TRADER_CASH,
    TRADER_COMMISSION,
    TRADER_DB,
    TRADER_DB_NAME,
    TRADER_EXCHANGE,
    TRADER_LEVERAGE_RATIO,
    TRADER_LIVE_ORDER_CLEANUP_SYMBOLS,
    TRADER_LOG_FILE,
    TRADER_LOG_LEVEL,
    TRADER_MIN_LIVE_TRADE_NOTIONAL,
    TRADER_MODE,
    TRADER_NOTICE,
    TRADER_PERIOD,
    TRADER_PLOT,
    TRADER_PROTECTED_PATHS,
    TRADER_REGISTRATION_ENABLED,
    TRADER_SECRET_KEY,
    TRADER_SESSION_COOKIE_SECURE,
    TRADER_SESSION_TTL_HOURS,
    TRADER_STAT,
    TRADER_TASKS,
    TRADER_WARMUP_CANDLES,
    TRADER_WINDOW,
    Config,
    parse_bool_config,
    parse_leverage_ratio_config,
    parse_log_file_config,
    parse_string_list_config,
)
from trader.core.shared.domain import NAME


def new_and_env(cli: Namespace | None = None) -> Config:
    """Build Config: built-in defaults, then environment variables, then explicit CLI flags (highest)."""

    commission = 0.001
    period = DEFAULT_PERIOD
    log_file = False
    plot = False
    mode = None
    log_level = "INFO"
    exchange = None
    db = None
    db_name = NAME
    window = 1000
    tasks = None
    cash = 100000.0
    stat = 50
    notice = None
    api = None
    auth_username = None
    auth_password = None
    protected_paths: list[str] = []
    secret_key = None
    session_cookie_secure = False
    session_ttl_hours = 24
    registration_enabled = True
    leverage_ratio = 1.0
    min_live_trade_notional = 11.0
    warmup_candles = 500
    live_order_cleanup_symbols: list[str] = []

    commission = float(os.environ.get(TRADER_COMMISSION, commission))
    period = int(os.environ.get(TRADER_PERIOD, period))
    log_file = parse_log_file_config(os.environ.get(TRADER_LOG_FILE, log_file))
    plot = os.environ.get(TRADER_PLOT, str(plot)).lower() == "true"
    mode = os.environ.get(TRADER_MODE, mode)
    log_level = os.environ.get(TRADER_LOG_LEVEL, log_level)
    exchange = os.environ.get(TRADER_EXCHANGE, exchange)
    db = os.environ.get(TRADER_DB, db)
    db_name = os.environ.get(TRADER_DB_NAME, db_name)
    window = int(os.environ.get(TRADER_WINDOW, window))
    tasks = os.environ.get(TRADER_TASKS, tasks)
    cash = float(os.environ.get(TRADER_CASH, cash))
    stat = int(os.environ.get(TRADER_STAT, stat))
    notice = os.environ.get(TRADER_NOTICE, notice)
    api = os.environ.get(TRADER_API, api)
    auth_username = os.environ.get(TRADER_AUTH_USERNAME, auth_username)
    auth_password = os.environ.get(TRADER_AUTH_PASSWORD, auth_password)
    secret_key = os.environ.get(TRADER_SECRET_KEY, secret_key)
    session_cookie_secure = parse_bool_config(os.environ.get(TRADER_SESSION_COOKIE_SECURE, session_cookie_secure))
    session_ttl_hours = int(os.environ.get(TRADER_SESSION_TTL_HOURS, session_ttl_hours))
    registration_enabled = parse_bool_config(
        os.environ.get(TRADER_REGISTRATION_ENABLED, registration_enabled), default=True, strict=True
    )
    leverage_ratio = parse_leverage_ratio_config(os.environ.get(TRADER_LEVERAGE_RATIO, leverage_ratio))
    min_live_trade_notional = float(os.environ.get(TRADER_MIN_LIVE_TRADE_NOTIONAL, min_live_trade_notional))
    warmup_candles = int(os.environ.get(TRADER_WARMUP_CANDLES, warmup_candles))
    live_order_cleanup_symbols = parse_string_list_config(os.environ.get(TRADER_LIVE_ORDER_CLEANUP_SYMBOLS, ""))

    protected_paths_env = os.environ.get(TRADER_PROTECTED_PATHS, "")
    if protected_paths_env:
        protected_paths = [path.strip() for path in protected_paths_env.split(",") if path.strip()]

    if cli is not None:
        a: dict[str, Any] = vars(cli)
        if "commission" in a:
            commission = float(a["commission"])
        if "period" in a:
            period = int(a["period"])
        if "log_file" in a:
            cli_log_file = a["log_file"]
            log_file = cli_log_file if isinstance(cli_log_file, str) else bool(cli_log_file)
        if "plot" in a:
            plot = bool(a["plot"])
        if "mode" in a:
            mode = a["mode"]
        if "log_level" in a:
            log_level = a["log_level"]
        if "exchange" in a:
            exchange = a["exchange"]
        if "db" in a:
            db = a["db"]
        if "db_name" in a:
            db_name = a["db_name"]
        if "window" in a:
            window = int(a["window"])
        if "tasks" in a:
            tasks = a["tasks"]
        if "cash" in a:
            cash = float(a["cash"])
        if "stat" in a:
            stat = int(a["stat"])
        if "notice" in a:
            notice = a["notice"]
        if "api" in a:
            api = a["api"]
        if "auth_username" in a:
            auth_username = a["auth_username"]
        if "auth_password" in a:
            auth_password = a["auth_password"]
        if "protected_paths" in a:
            raw_pp = a["protected_paths"]
            protected_paths = [p.strip() for p in raw_pp.split(",") if p.strip()] if raw_pp else []
        if "secret_key" in a:
            secret_key = a["secret_key"]
        if "session_cookie_secure" in a:
            session_cookie_secure = bool(a["session_cookie_secure"])
        if "session_ttl_hours" in a:
            session_ttl_hours = int(a["session_ttl_hours"])
        if "registration_enabled" in a:
            registration_enabled = bool(a["registration_enabled"])
        if "min_live_trade_notional" in a:
            min_live_trade_notional = float(a["min_live_trade_notional"])
        if "warmup_candles" in a:
            warmup_candles = int(a["warmup_candles"])
        if "live_order_cleanup_symbols" in a:
            live_order_cleanup_symbols = parse_string_list_config(a["live_order_cleanup_symbols"])

    return Config(
        commission=commission,
        period=period,
        log_file=log_file,
        plot=plot,
        mode=mode,
        log_level=log_level,
        exchange=exchange,
        db=db,
        db_name=db_name,
        window=window,
        tasks=tasks,
        cash=cash,
        stat=stat,
        notice=notice,
        api=api,
        auth_username=auth_username,
        auth_password=auth_password,
        protected_paths=protected_paths,
        secret_key=secret_key,
        session_cookie_secure=session_cookie_secure,
        session_ttl_hours=session_ttl_hours,
        registration_enabled=registration_enabled,
        leverage_ratio=leverage_ratio,
        min_live_trade_notional=min_live_trade_notional,
        warmup_candles=warmup_candles,
        live_order_cleanup_symbols=live_order_cleanup_symbols,
    )
