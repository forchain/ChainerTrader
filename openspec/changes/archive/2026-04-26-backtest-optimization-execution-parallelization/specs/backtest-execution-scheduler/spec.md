## ADDED Requirements

### Requirement: 参数优化运行必须采用两阶段受控调度

参数优化运行 SHALL 将“唯一数据集准备”和“样本回测执行”视为两个独立的调度阶段，而不是在样本展开时无限制地混合执行。

#### Scenario: 构建批量优化运行
- **WHEN** 一次参数优化任务被展开为多个样本
- **THEN** 系统 SHALL 先按 `(symbol, interval, start_time, end_time)` 去重出唯一数据集任务
- **AND** SHALL 在样本执行前完成这些数据集任务的调度与结果归档
- **AND** SHALL 仅为成功准备出 `dataset_ref` 的数据集创建依赖样本

### Requirement: 唯一数据集准备必须使用有限并行

系统 SHALL 对唯一数据集准备使用受控的并发上限，而不是串行逐个准备，也不是按数据集数无限制 fan-out。

#### Scenario: 唯一数据集数量超过准备并发上限
- **WHEN** 一次运行中的唯一数据集数量大于准备阶段的并发上限
- **THEN** 系统 SHALL 将超出的数据集任务排队
- **AND** SHALL 保证同时处于活动状态的数据集准备任务数不超过该上限
- **AND** SHALL 对同一数据集键只执行一次准备逻辑

#### Scenario: 某个数据集准备失败
- **WHEN** 某个唯一数据集在数据库检查、补数或缓存物化阶段失败
- **THEN** 系统 SHALL 将该数据集标记为准备失败
- **AND** SHALL 阻止所有依赖该数据集的样本进入执行阶段
- **AND** SHALL 为这些失败记录保留结构化失败原因

### Requirement: 样本回测必须使用基于 CPU 核数的进程池

系统 SHALL 使用基于 `os.cpu_count()` 的进程池执行参数优化样本回测，而不是按样本数直接创建并启动多个独立进程。

#### Scenario: 样本数量超过可用 worker 数
- **WHEN** 参数优化运行包含的样本数量大于进程池 worker 数
- **THEN** 系统 SHALL 将超出的样本任务排队
- **AND** SHALL 保证同时运行的样本 worker 数不超过有效的 `max_workers`
- **AND** SHALL 在已有 worker 完成后继续调度剩余样本

### Requirement: Worker 必须在子进程内部构造回测运行时对象

父进程 SHALL 向样本 worker 分发轻量任务规格；子进程 SHALL 基于 `dataset_ref` 和样本参数在本地构造 CSV 数据源、策略实例和回测执行对象。

#### Scenario: 提交样本任务到进程池
- **WHEN** 父进程向样本 worker 提交一个参数化回测样本
- **THEN** 提交内容 SHALL 包含 `dataset_ref`、策略标识、参数字典和报告上下文等轻量字段
- **AND** 不得要求父进程预先构造 `CSVData`、`Node` 或其他重型回测对象

#### Scenario: 多个 worker 复用同一 dataset_ref
- **WHEN** 多个参数化样本共享同一个 `dataset_ref`
- **THEN** 每个 worker SHALL 在自己的子进程中基于该 `dataset_ref` 独立创建回测运行时对象
- **AND** SHALL 不通过进程间传递完整 K 线对象来共享数据

### Requirement: 并行调度不得改变优化运行产物契约

并行调度 SHALL 保持 `optimization_run_id`、单次 JSON 报告、manifest、aggregate 和 failures 的现有契约兼容。

#### Scenario: 并发执行产生成功与失败混合结果
- **WHEN** 某次参数优化运行中部分样本成功、部分样本失败
- **THEN** 系统 SHALL 继续生成同一 `optimization_run_id` 下的运行目录
- **AND** SHALL 为成功样本保留原有单次报告与聚合输入
- **AND** SHALL 为失败样本保留原有失败记录结构
- **AND** SHALL 使 manifest 能同时引用成功与失败样本信息
