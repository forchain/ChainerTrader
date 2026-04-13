## 1. Scheduler Structure

- [x] 1.1 为参数优化运行定义两阶段调度模型：唯一数据集任务阶段与样本执行阶段
- [x] 1.2 抽象轻量级样本任务规格，明确 worker 输入边界
- [x] 1.3 保持普通单次回测配置的兼容行为不变

## 2. Dataset Preparation Parallelization

- [x] 2.1 提取唯一数据集任务集合，并继续按数据集键去重
- [x] 2.2 将唯一数据集准备改为有限并行，而不是逐个串行执行
- [x] 2.3 为阻塞数据库/API 调用提供受控并发执行机制，避免仅靠 coroutine fan-out
- [x] 2.4 为数据集准备失败建立对依赖样本的阻断与失败传播逻辑
- [x] 2.5 确保有限并行准备下仍可复用现有 `dataset_ref` 与透明缓存机制

## 3. Process Pool Backtest Execution

- [x] 3.1 将样本执行从“每样本一个独立 Process”改为基于 `os.cpu_count()` 的进程池
- [x] 3.2 将 `CSVData`、`Node` 和策略实例的构造迁移到子进程内部
- [x] 3.3 确保共享 `dataset_ref` 的多个样本可以在不同 worker 中独立消费
- [x] 3.4 确保样本数超过 worker 数时使用排队调度，而不是继续扩张进程数
- [x] 3.5 为 worker 结果定义可序列化返回载荷，统一回传日志、统计消息和样本报告

## 4. Result Compatibility

- [x] 4.1 保持 `optimization_run_id`、单次报告、聚合报告和失败记录目录结构兼容
- [x] 4.2 保持数据集准备失败与 worker 执行失败的结构化失败输出兼容
- [x] 4.3 验证并行调度不改变现有聚合报告输入语义

## 5. Automated Tests

- [x] 5.1 添加唯一数据集准备有限并行的测试
- [x] 5.2 添加样本执行遵守 `max_workers` 上限的测试
- [x] 5.3 添加 worker 在子进程内构造运行时对象的测试
- [x] 5.4 添加共享 `dataset_ref` 的多样本并发执行测试
- [x] 5.5 添加并发成功/失败混合场景下 manifest、aggregate 和 failures 兼容性测试
