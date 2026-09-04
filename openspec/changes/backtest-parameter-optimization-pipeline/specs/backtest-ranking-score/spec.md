## ADDED Requirements

### Requirement: 系统必须同时提供综合榜和超额收益榜

系统 SHALL 同时提供超额收益排名和综合评分排名，并暴露关键风险指标供人工与 Agent 共同判断。

#### Scenario: 查看参数组合榜单
- **WHEN** 用户或 Agent 读取优化结果
- **THEN** 系统 SHALL 提供 `by_excess_return` 榜单
- **AND** SHALL 提供 `by_score` 榜单
- **AND** 每个榜单条目 SHALL 同时展示收益、持有收益、超额收益、Sharpe、Profit Factor、Max Drawdown、交易次数和无交易样本数

### Requirement: 综合评分必须可解释且可版本化

综合评分 SHALL 使用带版本号的透明规则，而不是不可追溯的黑盒分数。

#### Scenario: 生成综合榜
- **WHEN** 系统生成综合评分排名
- **THEN** 聚合报告 SHALL 记录 `score_version`
- **AND** SHALL 记录每个参数组合的最终 `score`
- **AND** 评分规则 SHALL 对高回撤和无交易样本施加惩罚
- **AND** 在其他条件相近时，更高超额收益和更高跑赢持有比例的组合 SHALL 排名更高

### Requirement: 无交易样本必须显著影响综合排名

系统 SHALL 将无交易样本比例作为综合评分的惩罚项，以避免“无交易但因持有基准上涨而看似优秀”的组合获得过高排名。

#### Scenario: 高收益但无交易样本多的组合被降权
- **WHEN** 某参数组合拥有较高收益指标，但无交易样本比例显著高于其他组合
- **THEN** 该组合的综合评分 SHALL 低于同等超额收益但交易覆盖更高的组合
