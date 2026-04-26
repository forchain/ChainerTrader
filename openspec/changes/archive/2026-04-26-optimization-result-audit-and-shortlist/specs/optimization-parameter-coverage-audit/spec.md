## ADDED Requirements

### Requirement: 系统必须输出关键参数覆盖率审计结果

每次 optimization run 完成后，系统 SHALL 为关键参数输出覆盖率审计结果，包括取值覆盖、路径覆盖、触发机会、实际效果和最终状态。

#### Scenario: 优化运行后生成参数覆盖率审计
- **WHEN** 一个 optimization run 成功完成
- **THEN** 系统生成的审计产物中包含每个关键参数的 `tested_values`、`path_enter_count`、`opportunity_count`、`trigger_count`、`effect_count` 和 `status`

### Requirement: 系统必须区分未触发、被覆盖和可疑失效

当参数未产生行为差异时，系统 SHALL 区分其属于 `no_opportunity`、`inactive`、`shadowed_or_overridden` 或 `suspicious`，而不是统一标记为无效。

#### Scenario: 市场未提供触发机会
- **WHEN** 参数在同一 run 中存在多个取值，但其控制的逻辑从未遇到触发条件
- **THEN** 审计结果将该参数标记为 `no_opportunity`

#### Scenario: 参数逻辑被其他机制覆盖
- **WHEN** 参数理论上应影响风控或交易行为，且相关路径已执行，但最终行为被其他机制保持为一致
- **THEN** 审计结果将该参数标记为 `shadowed_or_overridden`

### Requirement: 系统必须识别参数已生效但最终收益未变的情况

如果参数变化导致中间状态变化，但最终收益没有变化，系统 SHALL 仍将其视为 `effective`。

#### Scenario: 参数改变了中间状态但未改变最终收益
- **WHEN** 不同参数组合导致止损价、止盈价、确认状态或其他中间字段发生变化，但 summary 指标保持一致
- **THEN** 审计结果将该参数标记为 `effective`，并记录变化字段
