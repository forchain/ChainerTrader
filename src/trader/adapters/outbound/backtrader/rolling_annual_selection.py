from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from trader.adapters.outbound.backtrader.optimization_runner import ProcessPoolBacktestRunner
from trader.adapters.outbound.binance.exchange import BinanceExchange
from trader.adapters.outbound.files.auto_coin_selection import DEFAULT_CONFIG_PATH
from trader.adapters.outbound.files.optimization_store import FileRankingReportStore, FileTaskConfigFileStore
from trader.adapters.outbound.persistence.manager import DatabaseManager
from trader.common.config import TRADER_DB, TRADER_EXCHANGE, TRADER_WARMUP_CANDLES, Config
from trader.common.logger import Logger
from trader.core.exchange.domain import parse_exchange_config
from trader.core.optimization.domain import (
    MonthWindow,
    SymbolRunResult,
    monthly_windows,
)
from trader.core.optimization.domain import (
    compounded_return_pct as _compounded_return_pct,
)
from trader.core.optimization.use_cases.selection import RollingAnnualSelectionUseCase

DEFAULT_YEAR = 2025
DEFAULT_REPORT_ID = "rolling_annual_selection_2025_cmc20"


async def _build_context():
    load_dotenv(Path(".env"))

    db_url = os.environ.get(TRADER_DB)
    exchange_payload = os.environ.get(TRADER_EXCHANGE)
    warmup_candles = int(os.environ.get(TRADER_WARMUP_CANDLES, 500) or 500)

    if not db_url:
        raise RuntimeError("TRADER_DB is required for rolling backtests")
    if not exchange_payload:
        raise RuntimeError("TRADER_EXCHANGE is required for rolling backtests")

    cfg = Config(
        db=db_url,
        exchange=exchange_payload,
        warmup_candles=warmup_candles,
        log_level="ERROR",
        cash=100000.0,
        window=1000,
    )
    log = Logger(cfg, 10000, True)
    db_manager = DatabaseManager(cfg, log)
    await db_manager.start()
    exchange_cfg = parse_exchange_config(exchange_payload)
    if exchange_cfg is None:
        raise RuntimeError("failed to parse TRADER_EXCHANGE")
    exchange = BinanceExchange(exchange_cfg, log)
    return cfg, log, db_manager, exchange


async def run_rolling_evaluation(
    *,
    year: int = DEFAULT_YEAR,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    output_dir: str | Path | None = None,
    report_id: str = DEFAULT_REPORT_ID,
) -> dict[str, Any]:
    cfg, log, db_manager, exchange = await _build_context()
    try:
        runner = ProcessPoolBacktestRunner(cfg=cfg, db_manager=db_manager, exchange=exchange, log=log)
        use_case = RollingAnnualSelectionUseCase(
            config_store=FileTaskConfigFileStore(),
            report_store=FileRankingReportStore(Path.cwd()),
            backtest_runner=runner,
            warmup_candles=cfg.warmup_candles,
        )
        return await use_case.execute(
            year=year,
            config_path=str(config_path),
            report_id=report_id,
            output_dir=str(output_dir) if output_dir is not None else None,
        )
    finally:
        await db_manager.stop()


def main() -> int:
    result = asyncio.run(run_rolling_evaluation())
    report_root = Path.cwd() / "reports" / "optimizations" / DEFAULT_REPORT_ID
    print(report_root / "summary.json")
    print(
        json.dumps(
            {
                "final_return_pct": result["final_return_pct"],
                "monthly_returns_pct": result["monthly_returns_pct"],
            },
            ensure_ascii=False,
        )
    )
    return 0


__all__ = [
    "DEFAULT_REPORT_ID",
    "DEFAULT_YEAR",
    "MonthWindow",
    "SymbolRunResult",
    "_compounded_return_pct",
    "main",
    "monthly_windows",
    "run_rolling_evaluation",
]

if __name__ == "__main__":
    raise SystemExit(main())
