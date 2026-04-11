## ADDED Requirements

### Requirement: 历史回测必须通过统一的数据准备机制获取数据

任何历史回测在执行前，系统 SHALL 根据 `symbol`、`interval`、`start_time` 和 `end_time` 准备所需数据集，而不是由具体业务流程各自实现数据库查询、补数和本地化逻辑。

#### Scenario: 数据库覆盖完整时直接复用
- **WHEN** 数据库已完整覆盖目标币种、周期和时间区间
- **THEN** 系统 SHALL 不调用交易所 API
- **AND** SHALL 从数据库读取该区间数据
- **AND** SHALL 将该区间物化为内部透明缓存
- **AND** SHALL 返回可供回测执行层复用的 `dataset_ref`

#### Scenario: 数据库覆盖不足时自动补数
- **WHEN** 数据库未完整覆盖目标币种、周期和时间区间
- **THEN** 系统 SHALL 自动调用交易所 API 获取缺失区间
- **AND** SHALL 将缺失数据写回数据库
- **AND** SHALL 在补数完成后重新从数据库读取完整区间
- **AND** SHALL 将完整区间物化为内部透明缓存
- **AND** SHALL 返回 `dataset_ref`

### Requirement: 数据覆盖检查必须识别区间内部缺口

系统 SHALL 校验目标时间区间的完整性，而不仅仅检查首条和末条 K 线是否存在。

#### Scenario: 首尾存在但中间缺口存在
- **WHEN** 目标区间的首条和末条 K 线存在，但中间缺少一个或多个连续 bar
- **THEN** 系统 SHALL 将该数据集判定为覆盖不足
- **AND** SHALL 自动补齐缺口后再开始回测

### Requirement: 数据准备按数据集键去重并复用缓存

系统 SHALL 以 `(symbol, interval, start_time, end_time)` 作为数据集键，对同一批回测中的数据准备请求去重。

#### Scenario: 多个参数组合共享同一数据集
- **WHEN** 多个回测任务仅参数不同，但请求相同的币种、周期和时间区间
- **THEN** 系统 SHALL 只执行一次数据准备
- **AND** SHALL 为这些任务复用同一份内部缓存
- **AND** SHALL 为这些任务返回相同的 `dataset_ref`

#### Scenario: 缓存已存在时直接复用
- **WHEN** 相同数据集键的内部缓存已存在且有效
- **THEN** 系统 SHALL 复用该缓存
- **AND** SHALL 不重复从数据库导出同一区间

### Requirement: 数据准备失败时不得启动依赖回测

系统 SHALL 在数据准备失败时阻止依赖该数据集的回测任务继续执行。

#### Scenario: API 补数失败
- **WHEN** 数据库覆盖不足且交易所 API 补数失败
- **THEN** 系统 SHALL 将该数据集标记为准备失败
- **AND** SHALL 不启动依赖该数据集的回测任务
- **AND** SHALL 在运行结果中明确暴露失败原因

### Requirement: 内部缓存对用户透明

系统 SHALL 将本地数据文件视为内部缓存产物，而不是要求用户显式维护的输入文件。

#### Scenario: 用户仅提供逻辑配置
- **WHEN** 用户仅配置币种、周期、时间区间、策略和参数空间
- **THEN** 系统 SHALL 自动完成数据库检查、补数、缓存物化和回测执行
- **AND** 不要求用户手工创建或维护 CSV 文件
