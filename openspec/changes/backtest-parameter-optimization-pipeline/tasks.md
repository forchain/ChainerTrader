## 1. Data Preparation Foundation

- [ ] 1.1 抽象统一的历史数据准备入口，输入 `(symbol, interval, start_time, end_time)` 并返回 `dataset_ref`
- [ ] 1.2 将现有数据库查询与自动补数逻辑迁移到数据准备入口，支持区间覆盖检查
- [ ] 1.3 为数据准备增加区间内部缺口检测与补齐逻辑
- [ ] 1.4 实现内部透明缓存物化与缓存命中复用逻辑
- [ ] 1.5 为数据准备失败建立结构化失败结果输出

## 2. Parameter Matrix Expansion

- [ ] 2.1 扩展任务配置，支持 `param_grid`
- [ ] 2.2 扩展任务配置，支持 `param_combinations`
- [ ] 2.3 实现 `param_combinations` 覆盖 `param_grid` 的优先级规则
- [ ] 2.4 为带参数搜索的任务条目增加“单策略约束”校验
- [ ] 2.5 为每个参数组合生成稳定的 `param_id`

## 3. Backtest Execution Integration

- [ ] 3.1 在回测执行前提取唯一数据集键并统一准备数据
- [ ] 3.2 让参数化回测任务复用 `dataset_ref` 而不是重复准备数据
- [ ] 3.3 将参数字典透传到策略实例构造过程
- [ ] 3.4 保持无参数搜索配置时的旧行为不变

## 4. Report Artifacts

- [ ] 4.1 为参数优化运行生成唯一的 `optimization_run_id`
- [ ] 4.2 创建 `reports/optimizations/<optimization_run_id>/` 目录化运行产物结构
- [ ] 4.3 增强单次回测 JSON 报告，增加 `optimization_run_id`、`report_version`、`param_id`、`params` 和 `dataset_ref`
- [ ] 4.4 生成 manifest 入口文件，汇总本次运行的样本、数据集和失败记录
- [ ] 4.5 实现按 `(strategy, params)` 聚合的优化报告输出

## 5. Ranking Views

- [ ] 5.1 在聚合结果中计算 `avg_excess_return_pct`、`median_excess_return_pct`、`beat_hold_ratio` 和 `no_trade_ratio`
- [ ] 5.2 实现 `score_v1` 计算并输出 `score_version`
- [ ] 5.3 生成 `by_score` 排名视图
- [ ] 5.4 生成 `by_excess_return` 排名视图
- [ ] 5.5 在榜单条目中展示关键风险与交易覆盖指标

## 6. Automated Tests

- [ ] 6.1 添加数据库覆盖完整时不触发 API 的数据准备测试
- [ ] 6.2 添加区间内部缺口检测与补齐测试
- [ ] 6.3 添加数据集键去重与缓存复用测试
- [ ] 6.4 添加 `param_grid` 笛卡尔积展开测试
- [ ] 6.5 添加 `param_combinations` 优先级测试
- [ ] 6.6 添加参数透传到策略实例的测试
- [ ] 6.7 添加聚合结果与排名视图测试
- [ ] 6.8 添加单次报告、聚合报告和 manifest 的报表契约测试

## 7. End-to-End Verification

- [ ] 7.1 使用缺失数据配置验证自动补数、写库和缓存物化的闭环
- [ ] 7.2 使用多参数、多币种、多周期配置验证同一 run 的样本聚合
- [ ] 7.3 验证单次样本报告、聚合报告、失败记录和 ranking 目录全部生成
- [ ] 7.4 验证 `optimization_run_id` 能串联 manifest、单次样本和聚合结果
