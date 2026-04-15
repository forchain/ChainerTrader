## Why

During large-scale backtesting and optimization runs, the user lacks visibility into the real-time status of individual worker processes and the overall CPU efficiency of the system. While the recent optimization runtime guardrails (PR #50) provide aggregated status data (`status.json`) and event streams (`events.jsonl`), there is no intuitive interface to view this data or to trace high CPU/memory usage back to the exact parameter combinations (task IDs) running on specific operating system PIDs. A terminal monitor will solve this visibility gap, making performance debugging and run progress monitoring much more effective.

## What Changes

1. **Terminal Dashboard Tool**: A new standalone tool, likely leveraging the `rich` Python library, will be created (e.g. `scripts/monitor_optimization.py`). It will provide a real-time terminal UI (TUI) displaying overall progress, expected/running worker counts, success/failure metrics, and per-worker status.
2. **Worker PID Exposure**: The underlying TaskManager and optimization runtime will be slightly augmented to allow worker processes to "announce" their OS PID upon task start (e.g., by creating lightweight `<pid>.json` files).
3. **PID-level CPU Tracking**: The dashboard will combine the PID mapping with `psutil` to show exactly how much CPU each active parameter sample is consuming.

## Capabilities

### New Capabilities
- `terminal-monitor`: A live terminal UI to observe the execution progress, worker states, and performance metrics of background optimization runs.
- `worker-pid-mapping`: An internal capability to map an executing optimization sample (task_id) to its backing OS Process ID (PID) without interfering with the parent-child executor IPC.

### Modified Capabilities

## Impact

- `src/trader/task/task_manager.py` or the specific worker execution functions (like `run_backtest_sample`) will need a small, non-blocking disk I/O step to write out their PID mapping.
- `src/trader/task/optimization_runtime.py` and existing `scripts/check_optimization_status.py` might be cleanly integrated or extended slightly to support the dashboard data requirements.
- A new dependency on `psutil` (if not already strictly required) might be added or optional for the scripting layer.
