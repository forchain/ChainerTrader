## 1. BacktestReportAnalyzer 核心实现

- [x] 1.1 创建 `src/trader/analyzers/` 目录并添加 `__init__.py`
- [x] 1.2 实现 `src/trader/analyzers/backtest_report.py`：继承 `bt.Analyzer`，在 `notify_trade()` 中收集逐笔交易记录（id、dir、entry/exit 时间价格、pnl_pct、reason、bars_held）
- [x] 1.3 在 `stop()` 中从 `self.strategy.analyzers` 读取 TradeAnalyzer、SharpeRatio、DrawDown、SQN 数据，计算 Profit Factor（处理无亏损交易的 null 情况）
- [x] 1.4 在 `stop()` 中计算月度 PnL（按交易平仓时间分组）和信号统计（total_signals、entered、confirm_failed）
- [x] 1.5 将完整 JSON 写入 `reports/<strategy>_<symbol>_<interval>_<YYYYMMDD_HHMMSS>.json`，确保 `reports/` 目录不存在时自动创建
- [x] 1.6 将 `reports/` 添加到 `.gitignore`

## 2. Node 集成

- [x] 2.1 在 `src/trader/strategy/node.py` 中 import `BacktestReportAnalyzer`
- [x] 2.2 在 `node.py` 的 `cerebro.addanalyzer()` 调用组中添加 `BacktestReportAnalyzer`，传入 strategy 名称、symbol、interval 参数
- [x] 2.3 运行 `bash scripts/backtest_cli.sh scripts/macd_triple_divergence.json` 验证 JSON 文件生成，检查字段完整性

## 3. 日志级别优化

- [x] 3.1 在 `src/trader/strategy/base_strategy.py` 中将 per-bar 例行日志（信号检测、确认检查等）从 `self.log.info()` 改为 `self.log.debug()`；保留开仓/平仓/止损/止盈为 INFO
- [x] 3.2 在 `src/trader/strategy/macd_triple_divergence.py` 中将「三段底背离检测」「信号触发」等 per-bar 日志降级为 DEBUG
- [x] 3.3 以默认 INFO 级别运行回测，验证日志输出不再包含每根 K 线的噪音日志

## 4. CLI 封装与数据集配置

- [x] 4.1 创建 `scripts/backtest_cli.sh`：内容为 `TRADER_API="" uv run python -m trader --tasks "$1"`，添加可执行权限
- [x] 4.2 创建 `scripts/backtest_train.json`：MACDTripleDivergence 策略，ETH-USDT 1h，`start_time: "2023-01-01"`, `end_time: "2023-09-30"`, csv 使用现有文件
- [x] 4.3 创建 `scripts/backtest_val.json`：MACDTripleDivergence 策略，ETH-USDT 1h，`start_time: "2023-10-01"`, `end_time: "2024-01-31"`, csv 使用现有文件
- [x] 4.4 创建 `scripts/download_2024_eth.json`：UPDATE_KLINES 任务，ETH-USDT，1h，`start_time: "2024-01-01"`, `end_time: "2024-12-31"`, `auto_download: true`
- [x] 4.5 创建 `scripts/backtest_test.json`：MACDTripleDivergence 策略，ETH-USDT 1h，`start_time: "2024-01-01"`, `end_time: "2024-12-31"`，数据源为 MongoDB（需先完成 4.4 下载）
- [x] 4.6 执行 `bash scripts/backtest_cli.sh scripts/backtest_train.json`，验证进程自动退出且生成 JSON 报告

## 5. 下载 2024 测试数据

- [x] 5.1 执行数据下载：`TRADER_API="" uv run python -m trader --tasks scripts/download_2024_eth.json`，等待完成
- [x] 5.2 验证 MongoDB 中 2024 数据可用：执行 `bash scripts/backtest_cli.sh scripts/backtest_test.json`，确认回测可正常运行

## 6. Baseline 建立

- [x] 6.1 执行训练集回测：`bash scripts/backtest_cli.sh scripts/backtest_train.json`，记录 JSON 报告中的 baseline 指标（Sharpe、Profit Factor、MaxDD、Total Trades）
- [x] 6.2 执行验证集回测：`bash scripts/backtest_cli.sh scripts/backtest_val.json`，记录验证集 baseline 指标
- [x] 6.3 在 `scripts/baseline.json` 中保存 baseline 指标记录，供 Skill 迭代时对比

## 7. Strategy-Optimize Skill 编写

- [x] 7.1 创建 `.claude/skills/strategy-optimize.md` skill 文件，包含以下章节：触发条件、前置检查清单、问题识别优先级框架（6 类问题的诊断逻辑）、One Change Rule 执行步骤、迭代循环流程图、防过拟合校验规则（每 5 轮）、停止条件（3 种）、回滚机制
- [x] 7.2 在 skill 中明确规定 Token 效率约束：只读 JSON 报告，不读日志文件，每轮目标 < 5000 tokens
- [x] 7.3 在 skill 中包含评估指标定义：主指标（Sharpe > 1.0，Profit Factor > 1.5）、硬约束（MaxDD < 20%，Trades ≥ 10）、防过拟合阈值（val_sharpe ≥ train_sharpe × 0.7）
- [x] 7.4 验证 skill 文件对低成本模型的可读性：每个步骤有明确的成功/失败判断标准，无需复杂推理

## 8. 端到端验证

- [x] 8.1 从零启动一次完整流程：运行训练集回测 → 读 JSON 报告 → 确认所有字段存在且数值合理
- [x] 8.2 验证 Skill 可触发：在新对话中调用 `strategy-optimize` skill，确认 skill 内容正确加载
- [x] 8.3 执行首轮手动优化迭代：根据 baseline JSON 报告识别最高优先级问题，提出一个假设并实施，比较前后指标
