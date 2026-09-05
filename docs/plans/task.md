| Task | Status | Description |
| --- | --- | --- |
| 1. Create unit tests for relative time range parsing | Completed | Write unit tests in `tests/test_time_range.py` for units (y, m, w, d, h), leap years, offsets |
| 2. Implement shared `time_range.py` module | Completed | Extract and implement `parse_relative_duration` and `resolve_time_range` in `src/trader/common/time_range.py` |
| 3. Integrate into `task_config.py` | Completed | Update `parse_task_config` to resolve relative `start_time` and `end_time` |
| 4. Update task config JSON | Completed | Update `configs/tasks/backtests/btc_4h_macd_triple_divergence_single.json` with `"start_time": "1y"` |
| 5. Add CLI task handling tests | Completed | Add tests in `tests/test_task_config_paths.py` for relative time in task config JSON |
| 6. Lint and test suite verification | Completed | Run ruff check and run pytest across affected test files |
| 7. Commit changes | Completed | Commit work with descriptive commit message referencing issue #159 |
