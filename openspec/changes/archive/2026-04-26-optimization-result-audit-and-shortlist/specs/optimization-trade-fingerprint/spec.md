## ADDED Requirements

### Requirement: 系统必须为每个优化样本生成稳定的交易行为指纹

每个 optimization sample SHALL 生成一个稳定的交易行为指纹，用于比较不同参数组合的真实执行行为。

#### Scenario: 完全相同行为生成相同指纹
- **WHEN** 两个样本的逐笔交易方向、入场时间、出场时间、出场价、持仓 bars 和退出原因完全一致
- **THEN** 两个样本的精确执行指纹相同

### Requirement: 指纹必须包含关键风控上下文

交易行为指纹 SHALL 不只包含逐笔成交结果，还必须包含框架风控和策略特殊退出所需的关键中间状态。

#### Scenario: 风控状态进入指纹
- **WHEN** 系统为样本生成指纹
- **THEN** 指纹原始字段中包含逐笔交易的 `framework_initial_stop_price`、`framework_final_stop_price`、`framework_tp_price` 以及退出原因代码

### Requirement: 指纹产物必须可供后续审计和聚类复用

系统 SHALL 将指纹以机器可读形式输出，而不是只在 HTML 视图中临时生成。

#### Scenario: 运行结束后输出指纹产物
- **WHEN** optimization run 完成
- **THEN** 系统生成 `fingerprints.json` 或等效结构化产物，供聚类和审计直接读取
