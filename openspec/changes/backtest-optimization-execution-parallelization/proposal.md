## Why

当前参数优化执行链路虽然已经支持展开大量样本，但在运行层仍然存在两个明显瓶颈：唯一数据集准备是顺序执行的，而样本回测执行则以“为每个样本直接拉起一个进程”的方式展开。对数百个样本的优化任务来说，这会让数据准备阶段成为串行瓶颈，也会让策略执行阶段出现进程过量、调度开销大、资源利用不稳定的问题。

现在需要把优化执行层升级为受控并行调度：让唯一数据集按有限并发准备，让样本回测按 CPU 核数受控并行执行，同时保持现有 `dataset_ref` 复用、报告产物和失败记录契约不变。

## What Changes

- 为参数优化运行引入独立的执行调度层，将“数据准备”和“样本执行”拆成两个受控并行阶段
- 将唯一数据集准备改为有限并行，而不是按 dataset key 串行依次准备
- 将样本回测执行改为 `max_workers = os.cpu_count()` 的进程池，而不是按样本数无限制创建进程
- 调整 worker 边界：父进程只分发轻量任务规格，子进程内部自行创建 `CSVData` / `Node` 并执行回测
- 保持单次报告、聚合报告、失败记录和 `optimization_run_id` 产物结构兼容
- 为调度层补充自动化测试，覆盖 worker 并发上限、数据集有限并行和失败传播

## Capabilities

### New Capabilities
- `backtest-execution-scheduler`: 为批量参数优化提供受控并行调度，负责唯一数据集的有限并行准备，以及样本回测的多核进程池执行

### Modified Capabilities
<!-- None -->

## Impact

- `src/trader/task/task_manager.py`
- `src/trader/task/backtrader_task.py`
- `src/trader/task/dataset_resolver.py`
- `src/trader/task/optimization_report.py`
- `tests/`
