## ADDED Requirements

### Requirement: 系统必须在同一 strategy-symbol-interval 组内聚类完全重复行为

系统 SHALL 在每个 `strategy + symbol + interval` 组内，对执行行为完全相同的参数组合建立重复行为簇。

#### Scenario: 同组内完全相同行为被归为同一簇
- **WHEN** 同一组内存在多个样本，其精确执行指纹完全相同
- **THEN** 系统将这些样本输出为同一个 `exact behavior cluster`

### Requirement: 系统必须为重复行为簇给出解释类型

每个完全重复行为簇 SHALL 被标记为合理重复、未触发重复、被覆盖重复或可疑重复中的一种。

#### Scenario: 参数未触发导致行为一致
- **WHEN** 一个重复行为簇对应的参数变化经审计判定为 `no_opportunity`
- **THEN** 该簇被标记为 `expected_same_behavior` 或等效未触发重复类型

#### Scenario: 参数被覆盖导致行为一致
- **WHEN** 一个重复行为簇对应的参数变化经审计判定为 `shadowed_or_overridden`
- **THEN** 该簇被标记为 `shadowed_behavior_cluster`

### Requirement: 每个行为簇必须选择代表组合

系统 SHALL 为每个行为簇选择一个代表参数组合，供后续 local best 与 shortlist 使用。

#### Scenario: 重复簇选择代表参数
- **WHEN** 系统完成行为聚类
- **THEN** 每个簇输出 `representative_param_id`，并将非代表成员标记为重复成员
