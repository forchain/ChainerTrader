## ADDED Requirements

### Requirement: 系统必须基于局部 winner 输出最终候选池

系统 SHALL 基于各组的局部最佳结果生成最终 shortlist，而不是直接从全量参数组合中取全局前 N。

#### Scenario: shortlist 只消费局部 winner
- **WHEN** 系统生成 shortlist
- **THEN** shortlist 的输入集合仅包含各组的 winner 或等效局部代表结果

### Requirement: shortlist 必须包含候选状态和解释

shortlist SHALL 为每个候选输出 `promote`、`watch` 或 `reject` 等状态，并附带入选或拒绝理由。

#### Scenario: 候选带状态与理由
- **WHEN** 一个组合进入 shortlist 产物
- **THEN** 该组合包含候选状态、入选原因、主要风险提示以及可能的替补项

### Requirement: shortlist 必须拒绝审计未通过的局部 winner

即使某个参数组合在组内是最佳结果，只要其审计状态不可信，系统 SHALL 阻止其进入最终 shortlist。

#### Scenario: 组内 winner 被阻止进入 shortlist
- **WHEN** 某组的 winner 带有高未分类退出率、关键参数失效或可疑重复标记
- **THEN** 该 winner 不进入最终 shortlist，并在产物中记录阻止原因
