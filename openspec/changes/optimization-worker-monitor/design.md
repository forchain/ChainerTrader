## Context

The optimization system within ChainerTrader uses a `ProcessPoolExecutor` to run many parameter backtest combinations concurrently. Currently, `OptimizationRuntimeStatus` aggregates overall progress and emits high-level events. However, because `ProcessPoolExecutor` hides process identifiers from the main thread during execution, it's impossible to map an ongoing backtest task to a specific operating system Process ID (PID). This makes pinpointing slow or resource-hogging parameter tasks exceptionally hard.

## Goals / Non-Goals

**Goals:**
- Output a precise mapping of `task_id` -> `OS PID` out of the running background samples.
- Build a lightweight, TUI-based (Terminal User Interface) monitor script that reads this mapping along with system performance data.
- Ensure the monitor clearly displays each worker's task context and its current per-process CPU usage.

**Non-Goals:**
- Interactive task termination: the dashboard is read-only.
- Replacing the standard multiprocessing executor or building complex Inter-Process Communication (IPC) sockets.
- Distributed worker monitoring (this only monitors the local machine running the optimization).

## Decisions

- **File-based Mapping (`<pid>.json`)**: Instead of passing custom pipes, the `run_backtest_sample` method will write an ephemeral `<pid>.json` into the run directory (`tmp/optimization_runs/<run_id>/workers/`) at the beginning of its job, containing its current `task_id`. It will delete it upon completion.
  *Rationale*: Extreme simplicity. It guarantees zero deadlocks or IPC overhead in the main event loop, and perfectly isolates the monitoring logic.
- **`rich` Terminal Library for UI**: The script `scripts/monitor_optimization.py` will use `rich.live.Live` and `rich.table.Table`. 
  *Rationale*: `rich` is standard for python modern TUIs, fast, dependency-light (often already present), and beautifully handles terminal resizing and layout mapping compared to manual `curses` code.
- **Side-Channel Polling**: The monitor script will read the worker files and call `psutil.Process(pid).cpu_percent()` directly. 
  *Rationale*: This fully decouples the heavy system calls from the critical path of the backtest execution framework.

## Risks / Trade-offs

- **Risk: Leftover `.json` files on hard crashes**: If a worker segfaults, the JSON mapping file might persist.
  *Mitigation*: The dashboard should tolerate reading a file for a PID that `psutil` catches a `NoSuchProcess` exception on. The main task manager will already report it failed/timed out in `events.jsonl`, but the dashboard can just ignore zombie PIDs gracefully.
