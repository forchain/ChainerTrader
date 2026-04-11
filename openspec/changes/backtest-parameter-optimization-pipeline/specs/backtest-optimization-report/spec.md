## ADDED Requirements

### Requirement: 参数优化运行必须生成可追溯的运行目录

每次参数优化运行完成后，系统 SHALL 生成以 `optimization_run_id` 为标识的运行目录，并包含适合机器分析的结构化报表。

#### Scenario: 一次优化运行完成
- **WHEN** 一次参数优化批量回测完成
- **THEN** 系统 SHALL 生成唯一的 `optimization_run_id`
- **AND** SHALL 输出该运行的目录化报表集合
- **AND** SHALL 提供该运行的入口清单文件

### Requirement: 单次回测报告必须包含参数与数据上下文

单次回测 JSON 报告 SHALL 在现有指标之外记录参数组合、参数标识、运行标识和数据集引用。

#### Scenario: 参数化回测生成单次报告
- **WHEN** 某个参数组合的单次回测完成
- **THEN** 报告 SHALL 包含 `optimization_run_id`
- **AND** SHALL 包含 `report_version`
- **AND** SHALL 包含 `param_id` 和 `params`
- **AND** SHALL 包含 `dataset_ref`
- **AND** SHALL 保留现有摘要指标、交易明细和信号明细

### Requirement: 系统必须生成按参数组合聚合的优化报告

系统 SHALL 按 `(strategy, params)` 聚合跨币种、跨周期的单次结果，并生成总榜输入数据。

#### Scenario: 同一参数组合跨样本聚合
- **WHEN** 相同策略参数在多个币种和多个周期上完成回测
- **THEN** 系统 SHALL 将这些单次结果聚合为同一个参数组合条目
- **AND** 聚合条目 SHALL 至少包含 `samples`、`total_trades`、`no_trade_samples`
- **AND** SHALL 包含 `avg_total_return_pct`、`avg_hold_return_pct`
- **AND** SHALL 包含 `avg_excess_return_pct` 和 `median_excess_return_pct`
- **AND** SHALL 包含 `beat_hold_ratio`、`avg_sharpe`、`avg_profit_factor`、`avg_max_dd_pct`

### Requirement: 优化运行必须记录失败样本

系统 SHALL 为数据准备失败或回测执行失败的样本保留结构化失败记录，而不是静默丢弃。

#### Scenario: 部分样本失败但运行继续
- **WHEN** 某些样本因数据准备失败或执行异常而无法完成
- **THEN** 系统 SHALL 将这些样本记录到运行目录中的失败记录集合
- **AND** SHALL 在 manifest 中反映失败样本数量与引用信息
