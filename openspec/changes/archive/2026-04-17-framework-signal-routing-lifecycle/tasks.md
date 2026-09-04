## 1. Framework Signal Contract

- [x] 1.1 在 `BaseStrategy` 中引入 per-bar signal snapshot 结构，并缓存当前 bar 的 long/short signal 与对应 context
- [x] 1.2 在 `BaseStrategy` 中新增 signal lifecycle 扩展点，允许策略观察 detected、blocked、entry_context_created、entry_context_cancelled 和 exit_requested 等 outcome
- [x] 1.3 明确 `BaseStrategy._process_signals()` 为框架独占的 signal routing 入口，并保持 `LONG_ONLY` / `SHORT_ONLY` / `BOTH` 语义集中在框架层

## 2. Shared Flow Integration

- [x] 2.1 将 `_process_signals()` 切换为消费当前 bar 的 signal snapshot，而不是直接重复调用 signal getter
- [x] 2.2 将 `_process_trade_engine()` 中 pending entry confirmation 的 opposing signal 判断切换为复用同一份 signal snapshot
- [x] 2.3 确保 signal context 只在对应 signal 触发时通过统一接口求值一次，并通过 snapshot / trade context 继续传递

## 3. Strategy Migration Sample

- [x] 3.1 重构 `macd_triple_divergence`，移除对 `_process_signals()` override 的依赖
- [x] 3.2 将 `macd_triple_divergence` 的 signal outcome 记录迁移到新的 framework lifecycle hook / shared contract
- [x] 3.3 保持 `macd_triple_divergence` 现有私有退出规则、pending entry 跟踪和 signal metadata 行为与新框架 contract 兼容

## 4. Regression Coverage

- [x] 4.1 添加 `BaseStrategy` 级别的 mode routing 回归测试，覆盖 `LONG_ONLY`、`SHORT_ONLY` 和 `BOTH`
- [x] 4.2 添加同一根 bar 内 signal 只求值一次、确认流程复用 snapshot 的回归测试
- [x] 4.3 添加 signal lifecycle hook / outcome callback 的回归测试，覆盖 blocked 与 entry context outcome
- [x] 4.4 添加 `LONG_ONLY` 下 short signal 不触发 short entry 的策略回归测试，并验证 `macd_triple_divergence` 通过共享框架流程运行
