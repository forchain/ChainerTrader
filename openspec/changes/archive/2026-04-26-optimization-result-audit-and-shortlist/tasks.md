## 1. Backtest Report Foundations

- [x] 1.1 扩展单次回测 JSON 报告，使逐笔交易记录完整包含退出原因、风控中间状态和行为指纹所需字段
- [x] 1.2 清理“其他原因退出”兜底逻辑，统一改为未分类退出，并为所有已知退出路径补足明确原因
- [x] 1.3 为关键参数和关键退出路径补充基线测试，验证参数差异会改变中间状态或交易行为

## 2. Parameter Coverage Audit

- [x] 2.1 定义关键参数的覆盖率证据模型和统一状态枚举（effective/no_opportunity/inactive/shadowed_or_overridden/suspicious）
- [x] 2.2 实现关键参数覆盖率统计，输出取值覆盖、路径覆盖、触发机会和实际效果
- [x] 2.3 生成 `audit.json`，并在基线优化运行中验证可疑参数会被标记出来

## 3. Trade Fingerprints And Behavior Clustering

- [x] 3.1 生成每个优化样本的精确交易行为指纹，并输出 `fingerprints.json`
- [x] 3.2 在 `strategy + symbol + interval` 组内实现完全重复行为聚类
- [x] 3.3 为重复行为簇补充解释类型、代表组合选择和 `clusters.json` 输出

## 4. Local Best Selection

- [x] 4.1 定义局部最优的过滤规则，先排除审计失败、可疑重复和明显不适合实盘的组合
- [x] 4.2 按 `strategy + symbol + interval` 选择局部 winner，并输出 runner-up / rejected 的原因
- [x] 4.3 生成 `local_best.json`，并补充对应的自动化验证

## 5. Shortlist Reporting

- [x] 5.1 基于局部 winner 生成最终 shortlist JSON，输出 promote/watch/reject 状态、入选理由和风险提示
- [x] 5.2 生成基础 shortlist HTML 视图，面向人工验收而不是全量排名浏览
- [x] 5.3 确保 shortlist 不会直接消费全量参数组合，只使用局部 winner 作为输入

## 6. Long-Running Verification Workflow

- [x] 6.1 新增基线优化审计脚本，运行后自动生成 audit / clusters / local_best / shortlist 产物
- [x] 6.2 将参数覆盖率异常、未分类退出和可疑重复簇作为 workflow 阻断条件
- [x] 6.3 为 Agent 复核预留标准输入摘要，让脚本审计通过后再进入语义审查
