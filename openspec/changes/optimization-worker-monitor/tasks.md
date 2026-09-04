## 1. Implement Worker PID Mapping

- [x] 1.1 Modify `run_backtest_sample` in `src/trader/task/backtrader_task.py` to write `{"task_id": <task_id>, "started_at": <timestamp>}` to `tmp/optimization_runs/<run_id>/workers/<pid>.json` at the start of execution.
- [x] 1.2 Modify `run_backtest_sample` with a `try...finally` block to assure the deletion of the `<pid>.json` file when execution completes or crashes.
- [x] 1.3 Update the relevant tests (e.g., in `tests/test_optimization_runtime.py` or new file) to verify the PID metadata lifecycle during sample execution.

## 2. Build the Terminal Dashboard

- [x] 2.1 Create the executable script `scripts/monitor_optimization.py` and configure CLI argument parsing (accepts specific `--run-id` or falls back to latest).
- [x] 2.2 Implement the internal data aggregator to efficiently read `status.json` and the active `workers/*.json` pool.
- [x] 2.3 Implement CPU and Memory querying using the `psutil` package against the discovered PIDs, ensuring graceful handling of missing or defunct processes.
- [x] 2.4 Build the `rich` UI layout (`rich.live.Live` and `rich.table.Table`) incorporating a global overview panel (progress, host CPU) and a granular workers table (task_id, CPU%, Mem%).
- [x] 2.5 Tie the data aggregator and `rich` UI layout together in an async or blocking refresh loop to update the dashboard continuously until the optimization terminates or user aborts (Ctrl+C).
