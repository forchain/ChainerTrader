"""CSV dataset file-store adapter."""

from __future__ import annotations

import csv
from pathlib import Path

from trader.core.shared.domain import Kline


class CsvDatasetFileStore:
    def write_klines(self, path: Path, klines: list[Kline]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp")
        try:
            with tmp_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                for kl in klines:
                    writer.writerow(
                        [
                            kl.open_time * 1000,
                            kl.open,
                            kl.high,
                            kl.low,
                            kl.close,
                            kl.volume,
                            kl.close_time * 1000,
                            kl.vol_quote,
                            kl.trades,
                            kl.vol_taker_base,
                            kl.vol_taker_quote,
                            kl.ignore,
                        ]
                    )
            tmp_path.replace(path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def count_klines(self, path: Path) -> int:
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                return sum(1 for _ in csv.reader(handle))
        except OSError:
            return -1

    def read_rows(self, path: Path) -> list[list[str]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.reader(handle))
