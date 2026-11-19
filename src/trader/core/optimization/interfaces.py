from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BacktestRunner(Protocol):
    async def prepare_datasets(self, configs: list[Any], runtimes: dict[str, Any] | None = None) -> list[dict]: ...

    async def execute_samples(self, sample_specs: list[Any]) -> list[Any]: ...


@runtime_checkable
class RankingReportStore(Protocol):
    def load_sample_reports(self, run_id: str) -> list[dict]: ...

    def load_failures(self, run_id: str) -> list[dict]: ...

    def write_artifacts(self, run_id: str, sample_reports: list[dict], failures: list[dict]) -> dict: ...

    def write_agent_review_summary(self, run_id: str, summary: dict) -> str: ...

    def write_rolling_outputs(
        self,
        report_id: str,
        summary: dict,
        monthly_items: list[dict],
        output_dir: str | None = None,
    ) -> None: ...


@runtime_checkable
class TaskConfigFileStore(Protocol):
    def exists(self, path: str) -> bool: ...

    def load_json(self, path: str) -> Any: ...

    def write_json(self, path: str, payload: Any) -> None: ...

    def read_lines(self, path: str, limit: int) -> list[str]: ...


@runtime_checkable
class CandidateSymbolSource(Protocol):
    def fetch_binance_exchange_info(self) -> dict[str, Any]: ...

    def fetch_cmc_index(self, index: str) -> dict[str, Any]: ...
