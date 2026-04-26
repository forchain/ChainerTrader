## ADDED Requirements

### Requirement: 系统必须为关键 Chainer 参数生成人工可观察状态

系统 SHALL 为关键 `Chainer` 参数生成面向人工验证的观察状态。每个状态 MUST 属于 `has_evidence`、`not_triggered`、`no_evidence`、`suspicious` 之一，并附带简要证据摘要。

#### Scenario: 关键参数生成观察状态
- **WHEN** optimization run 的 workbench 数据被生成
- **THEN** 每个候选项都包含关键参数的观察状态与证据摘要

### Requirement: 参数观察必须基于参数类型输出对应证据

系统 SHALL 按参数类型输出对应的可观察证据，而不是只暴露统一的原始字段集合。至少覆盖确认类、止损类、止盈类、保本类、账户约束类参数。

#### Scenario: 确认参数输出时间类证据
- **WHEN** `chainer_need_confirm` 出现在候选参数中
- **THEN** 该参数的观察结果包含信号时间与执行时间是否分离的证据摘要

#### Scenario: 最小余额参数输出数量与拦截类证据
- **WHEN** `chainer_min_equity_percent` 出现在候选参数中
- **THEN** 该参数的观察结果包含仓位数量、余额保护阻断或后续开仓变化等证据摘要

### Requirement: 参数观察必须突出可疑信号

系统 SHALL 为每个关键参数生成可疑信号列表，用于提示用户哪些行为值得进一步打开原始报告核验。

#### Scenario: 参数没有留下预期痕迹时标记可疑
- **WHEN** 参数存在配置差异但在候选结果中没有留下对应的观察证据
- **THEN** 该参数的观察结果被标记为 `suspicious` 或 `no_evidence`，并附带可疑信号说明
