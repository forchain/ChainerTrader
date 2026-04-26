## ADDED Requirements

### Requirement: 系统必须按 strategy-symbol-interval 选择局部最佳参数

系统 SHALL 以 `strategy + symbol + interval` 为唯一分组单位，在每个组内选择一个局部最佳参数组合。

#### Scenario: 每组最多输出一个 winner
- **WHEN** 一个组内存在多个通过基础执行的参数组合
- **THEN** 系统在该组内最多输出一个 `winner` 作为局部最佳参数

### Requirement: 局部最佳选择必须先过滤异常和不适合实盘的结果

在组内选择最佳参数前，系统 SHALL 先过滤掉审计失败、可疑重复或明显不适合实盘的参数组合。

#### Scenario: 可疑组合不参与组内最优选择
- **WHEN** 某个参数组合被标记为 `suspect`、`shadowed_behavior_cluster` 或等效高风险状态
- **THEN** 该组合不参与组内 winner 竞争

### Requirement: 局部最佳结果必须解释为什么入选和为什么未入选

局部最佳产物 SHALL 同时输出 winner 的入选原因和其他候选未入选的原因。

#### Scenario: 组内 winner 带解释信息
- **WHEN** 系统为某个组输出 winner
- **THEN** 产物中包含 `selection_reasons`，并为 runner-up 或 rejected 候选输出 `why_not_selected`

### Requirement: 系统必须允许某个组没有有效 winner

如果一个组内没有任何可信且适合实盘的候选，系统 SHALL 明确输出该组没有有效 winner，而不是强行选择一个结果。

#### Scenario: 全组被过滤时输出 no_valid_winner
- **WHEN** 某组内所有候选都被审计或实盘过滤规则排除
- **THEN** 该组输出 `no_valid_winner`
