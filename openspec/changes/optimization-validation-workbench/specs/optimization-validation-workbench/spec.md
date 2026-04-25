## ADDED Requirements

### Requirement: 系统必须输出动态 workbench 专用的 run 聚合数据

系统 SHALL 为每个 optimization run 生成 `workbench.json`，作为人工验证 workbench 的唯一主数据入口。该文件 MUST 包含 run 摘要、候选项列表、参数观察摘要、紧凑交易明细和原始报告链接。

#### Scenario: optimization run 生成 workbench 聚合入口
- **WHEN** 一个 optimization run 完成并写出报告产物
- **THEN** `reports/optimizations/<run_id>/workbench.json` 被生成

#### Scenario: workbench 聚合入口包含候选扫描所需字段
- **WHEN** workbench 读取 `workbench.json`
- **THEN** 每个候选项都包含 `param_id`、`strategy`、`symbol`、`interval`、核心 summary 指标、参数摘要、参数观察摘要和原始 report 链接

### Requirement: workbench 必须按验证任务组织候选详情

动态 workbench SHALL 将候选详情拆分为 `参数观察`、`交易明细`、`审计上下文` 三个视图，而不是继续以长表平铺字段。

#### Scenario: 候选详情优先展示参数观察
- **WHEN** 用户展开一个候选项
- **THEN** workbench 默认展示 `参数观察` 视图

#### Scenario: 候选详情提供逐笔交易验证视图
- **WHEN** 用户切换到 `交易明细`
- **THEN** workbench 展示紧凑语义列布局的逐笔交易表，而不是单字段长表

### Requirement: workbench 必须提供原始报告深查入口

系统 SHALL 在每个候选项中提供可直接打开原始 `runs/*.json` 报告的入口，供用户在定性验证后快速深查。

#### Scenario: 用户从候选详情打开原始 report
- **WHEN** workbench 渲染候选详情
- **THEN** 页面中存在可点击的原始 report 链接，目标指向该候选对应的 run 报告文件
