#!/usr/bin/env python3
"""Real-time terminal dashboard for a running optimization job.

Usage:
    uv run python scripts/monitor_optimization.py --run-id <run_id>
    uv run python scripts/monitor_optimization.py          # auto-detects latest run

Requires:
    rich>=13.0
    psutil>=5.9
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text


REFRESH_HZ = 2  # dashboard refresh rate
WORKERS_SUBDIR = "workers"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimization run dashboard")
    parser.add_argument("--run-id", help="Optimization run id (auto-detected if omitted)")
    parser.add_argument(
        "--runs-dir",
        default=None,
        help="Directory containing optimization run dirs (default: <cwd>/tmp/optimization_runs)",
    )
    parser.add_argument(
        "--refresh",
        type=float,
        default=1.0 / REFRESH_HZ,
        help=f"Refresh interval in seconds (default: {1.0 / REFRESH_HZ:.2f})",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Data aggregation
# ---------------------------------------------------------------------------


def _runs_dir(custom: str | None) -> Path:
    base = Path(custom) if custom else Path.cwd() / "tmp" / "optimization_runs"
    return base


def _latest_run_id(runs_dir: Path) -> str | None:
    """Return the run_id with the most-recently modified status.json, or None."""
    candidates = []
    if not runs_dir.exists():
        return None
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        status_path = run_dir / "status.json"
        if status_path.exists():
            candidates.append((status_path.stat().st_mtime, run_dir.name))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_status(run_dir: Path) -> dict[str, Any]:
    status = _read_json(run_dir / "status.json") or {}
    return status


def _read_workers(run_dir: Path) -> list[dict[str, Any]]:
    """Return list of active worker payloads from workers/<pid>.json files."""
    workers_dir = run_dir / WORKERS_SUBDIR
    workers = []
    if not workers_dir.exists():
        return workers
    for pid_file in workers_dir.glob("*.json"):
        payload = _read_json(pid_file)
        if payload:
            workers.append(payload)
    return workers


def _enrich_workers_with_psutil(workers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add cpu_pct and mem_mb fields to each worker entry using psutil."""
    if psutil is None:
        for w in workers:
            w["cpu_pct"] = None
            w["mem_mb"] = None
        return workers

    enriched = []
    for w in workers:
        pid = w.get("pid")
        try:
            proc = psutil.Process(pid)
            # cpu_percent returns 0.0 on first call; interval=None is non-blocking
            cpu = proc.cpu_percent(interval=None)
            mem = proc.memory_info().rss / 1024 / 1024
            w["cpu_pct"] = round(cpu, 1)
            w["mem_mb"] = round(mem, 1)
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError):
            w["cpu_pct"] = None
            w["mem_mb"] = None
        enriched.append(w)
    return enriched


# ---------------------------------------------------------------------------
# UI building blocks
# ---------------------------------------------------------------------------


def _status_color(stage: str) -> str:
    if stage in ("finished",):
        return "bold green"
    if stage in ("aborted",):
        return "bold red"
    if stage in ("sample_execution",):
        return "bold cyan"
    if stage in ("dataset_preparation",):
        return "bold yellow"
    return "white"


def _health_color(health: str) -> str:
    return "bold green" if health == "healthy" else "bold red"


def _build_overview_panel(status: dict[str, Any], run_id: str) -> Panel:
    stage = status.get("stage", "unknown")
    health = status.get("health", "unknown")
    elapsed = status.get("elapsed_seconds", 0)
    total = status.get("samples_total", 0)
    completed = status.get("samples_completed", 0)
    succeeded = status.get("samples_succeeded", 0)
    failed = status.get("samples_failed", 0)
    timed_out = status.get("samples_timed_out", 0)
    skipped = status.get("samples_skipped", 0)
    running = status.get("samples_running", 0)
    expected_workers = status.get("expected_workers", 0)
    running_workers = status.get("running_workers", 0)
    host_cpu = status.get("host_cpu_pct", 0.0)
    failure_rate = status.get("failure_rate", 0.0)
    spm = status.get("samples_per_minute", 0.0)
    p_ratio = status.get("parallelism_ratio", 0.0)
    abort_reason = status.get("abort_reason")

    pct = int(completed / total * 100) if total else 0

    text = Text()
    text.append(f"Run ID : ", style="dim")
    text.append(f"{run_id}\n", style="bold white")
    text.append(f"Stage  : ", style="dim")
    text.append(f"{stage}\n", style=_status_color(stage))
    text.append(f"Health : ", style="dim")
    text.append(f"{health}", style=_health_color(health))
    if abort_reason:
        text.append(f"  ({abort_reason})", style="red")
    text.append("\n")
    text.append(f"Elapsed: ", style="dim")
    text.append(f"{elapsed}s\n", style="white")
    text.append("\n")

    # Progress bar row
    bar_filled = int(pct / 2)
    bar = "█" * bar_filled + "░" * (50 - bar_filled)
    text.append(f"Progress : [{bar}] {pct}% ({completed}/{total})\n", style="cyan")
    text.append(f"Speed    : {spm:.1f} samples/min\n", style="dim")
    text.append("\n")

    # Samples table
    text.append(f"✅ Succeeded : {succeeded:<6}", style="green")
    text.append(f"❌ Failed    : {failed + timed_out:<6}", style="red")
    text.append(f"⏭  Skipped   : {skipped:<6}\n", style="yellow")
    text.append(f"▶  Running   : {running:<6}", style="cyan")
    text.append(f"📉 FailRate  : {failure_rate * 100:.1f}%\n", style="magenta")
    text.append("\n")

    # Workers & CPU
    text.append(f"Workers (running/expected) : ", style="dim")
    worker_color = "green" if running_workers >= expected_workers * 0.8 else "red"
    text.append(f"{running_workers}/{expected_workers}  ", style=f"bold {worker_color}")
    text.append(f"Parallelism: {p_ratio * 100:.0f}%\n", style="dim")
    text.append(f"Host CPU : ", style="dim")
    cpu_color = "green" if host_cpu < 80 else "yellow" if host_cpu < 95 else "red"
    text.append(f"{host_cpu:.1f}%  (psutil-per-worker below)\n", style=cpu_color)

    return Panel(text, title="[bold cyan]Optimization Overview[/bold cyan]", border_style="cyan", padding=(0, 1))


def _build_workers_table(workers: list[dict[str, Any]]) -> Table:
    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold cyan",
        title="Active Workers",
        title_style="bold white",
        expand=True,
    )
    table.add_column("PID", style="dim", width=8)
    table.add_column("Task ID", width=9)
    table.add_column("Run ID", style="dim", max_width=28)
    table.add_column("CPU %", width=8, justify="right")
    table.add_column("Mem MB", width=9, justify="right")
    table.add_column("Started At", style="dim", width=22)

    if not workers:
        table.add_row("—", "—", "—", "—", "—", "—")
        return table

    for w in sorted(workers, key=lambda x: x.get("task_id", 0)):
        pid = str(w.get("pid", "?"))
        task_id = str(w.get("task_id", "?"))
        run_id = str(w.get("run_id", "?"))
        cpu_pct = w.get("cpu_pct")
        mem_mb = w.get("mem_mb")

        cpu_str = f"{cpu_pct:.1f}%" if cpu_pct is not None else "n/a"
        mem_str = f"{mem_mb:.1f}" if mem_mb is not None else "n/a"

        cpu_style = "green"
        if cpu_pct is not None:
            cpu_style = "green" if cpu_pct >= 50 else "yellow" if cpu_pct >= 10 else "red"

        started = w.get("started_at", "")
        table.add_row(pid, task_id, run_id, Text(cpu_str, style=cpu_style), mem_str, started)

    return table


def _build_layout(run_id: str, status: dict[str, Any], workers: list[dict[str, Any]]) -> Columns:
    overview = _build_overview_panel(status, run_id)
    workers_table = _build_workers_table(workers)
    return Columns([overview, workers_table], expand=True, equal=True)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _is_terminal(status: dict[str, Any]) -> bool:
    return status.get("stage") in ("finished", "aborted")


def main() -> int:
    args = parse_args()
    runs_dir = _runs_dir(args.runs_dir)

    run_id = args.run_id
    if not run_id:
        run_id = _latest_run_id(runs_dir)
    if not run_id:
        print("No active optimization run found. Use --run-id to specify one.")
        return 1

    run_dir = runs_dir / run_id
    if not run_dir.exists():
        print(f"Run directory not found: {run_dir}")
        return 1

    console = Console()

    if psutil is not None:
        # Prime psutil CPU measurement (first call always returns 0.0)
        for proc in psutil.process_iter(["pid"]):
            try:
                proc.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        time.sleep(args.refresh / 2)

    with Live(console=console, refresh_per_second=REFRESH_HZ, screen=False) as live:
        while True:
            status = _read_status(run_dir)
            workers = _read_workers(run_dir)
            workers = _enrich_workers_with_psutil(workers)

            layout = _build_layout(run_id, status, workers)
            live.update(layout)

            if _is_terminal(status):
                time.sleep(args.refresh)
                # Final render after terminal stage
                status = _read_status(run_dir)
                workers = _read_workers(run_dir)
                workers = _enrich_workers_with_psutil(workers)
                live.update(_build_layout(run_id, status, workers))
                console.print(
                    f"\n[bold]Run [cyan]{run_id}[/cyan] has [{'green' if status.get('stage') == 'finished' else 'red'}]{status.get('stage', 'ended')}[/]. Exiting monitor.[/bold]"
                )
                break

            time.sleep(args.refresh)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
