## ADDED Requirements

### Requirement: TUI Dashboard Display
The `monitor_optimization.py` script must render a live-updating console interface displaying overall optimization progress and individual worker status.

#### Scenario: Active parallel execution
- **WHEN** an optimization task is running in the background.
- **THEN** the dashboard should show the global percentage completion, elapsed time, running workers count, and aggregate CPU utilization.
- **THEN** beneath the global statistics, the dashboard should list each active worker task, its CPU usage, and memory consumption.
