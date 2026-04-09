#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency outside uv-managed envs
    def load_dotenv() -> bool:
        return False

from trader.scanner.top_volume_signal_scanner import (
    build_runtime_config,
    dump_signals_json,
    render_signal_table,
    scan_market_report,
)
from trader.strategy.strategy import parse_strategy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan top-volume Binance spot USDT pairs and print triggered strategy signals."
    )
    parser.add_argument(
        "--strategy",
        default="macd_triple_divergence",
        help="Strategy name to scan. Defaults to macd_triple_divergence.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of top-volume Binance spot USDT pairs to scan.",
    )
    parser.add_argument(
        "--json-out",
        type=str,
        default=None,
        help="Optional path to write structured JSON results.",
    )
    args = parser.parse_args()
    if args.top <= 0:
        parser.error("--top must be greater than 0")
    if parse_strategy(args.strategy) is None:
        parser.error(f"Unsupported strategy: {args.strategy}")
    return args


def main() -> int:
    load_dotenv()
    args = parse_args()
    cfg, logger, db_manager, exchange = build_runtime_config()
    try:
        report = asyncio.run(
            scan_market_report(
                cfg,
                logger,
                db_manager,
                exchange,
                top_n=args.top,
                strategy_name=args.strategy,
            )
        )
        print(render_signal_table(report["signals"]))
        if args.json_out:
            output = dump_signals_json(Path(args.json_out), report)
            print(output)
        return 0
    finally:
        db_manager.stop()


if __name__ == "__main__":
    raise SystemExit(main())
