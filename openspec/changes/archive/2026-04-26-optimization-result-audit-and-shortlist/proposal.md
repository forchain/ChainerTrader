## Why

ChainerTrader 现有的优化报表主要用于展示批量回测结果，但还不能稳定支持“从大量组合中筛出可用于实盘的优质候选”。当参数未生效、交易行为重复、退出原因缺失或结果存在明显异常时，系统不会主动审计和报警，导致优化结果表面可排序、实际不可信。

这次变更的目标是把优化结果输出升级为一个完整的可信度闭环：先审计参数是否真实生效、交易行为是否异常重复、退出原因是否完整分类，再按 `strategy + symbol + interval` 选择局部最佳参数，并输出可直接服务实盘决策的 shortlist。

## What Changes

- 新增优化结果审计层，对关键参数的覆盖率、触发机会、实际效果和可疑失效进行结构化分析
- 新增交易行为指纹和行为聚类能力，识别完全重复或高度相似的参数组合，并区分合理重复与可疑重复
- 新增按 `strategy + symbol + interval` 的局部最优选择逻辑，先过滤异常和高风险结果，再选每组最佳参数
- 新增 shortlist 产物，输出面向实盘决策的候选、替补和剔除原因，而不是只给出全局排名表
- 强化单次回测 JSON 报告，补足框架风控、策略特殊退出和逐笔退出原因等审计所需上下文
- 调整优化运行 workflow，让基线运行、审计脚本和 Agent 复核形成长期可独立迭代的闭环

## Capabilities

### New Capabilities
- `optimization-parameter-coverage-audit`: 统计关键参数的取值覆盖、路径覆盖、触发机会和实际效果，识别未触发、被覆盖或疑似失效的参数
- `optimization-trade-fingerprint`: 为每个优化样本生成可比较的交易行为指纹，供异常检测、聚类和候选筛选使用
- `optimization-behavior-clustering`: 按交易行为而不是参数值对组合聚类，标记合理重复、未触发重复和可疑重复
- `optimization-local-best-selection`: 按 `strategy + symbol + interval` 选择局部最佳参数，并给出未入选原因
- `optimization-shortlist-report`: 基于审计和局部最优结果输出最终候选池，包含候选、替补、风险提示和拒绝理由

### Modified Capabilities
- `backtest-json-report`: 单次回测 JSON 报告增加退出原因、风控中间状态和生成交易行为指纹所需字段

## Impact

- `src/trader/analyzers/backtest_report.py`
- `src/trader/task/optimization_report.py`
- `src/trader/strategy/base_strategy.py`
- `src/trader/strategy/macd_triple_divergence.py`
- `src/trader/task/`
- `reports/optimizations/<run_id>/`
- `tests/`
- `scripts/`
- 优化结果审查与发布 workflow
