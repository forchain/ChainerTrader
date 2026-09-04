## Context

ChainerTrader 是一个基于 Backtrader 框架的算法交易系统。回测通过 `BackTraderTask` → `Node` → `cerebro.run()` 执行，Node 中已注册 `TradeAnalyzer`、`DrawDown`、`SharpeRatio`、`VWR` 等标准 Backtrader 分析器，但结果仅格式化为 PrettyTable 输出到终端日志，无结构化文件输出。策略的 per-bar 日志以 INFO 级别打印，导致 9500 根 K 线产生 >34MB 日志，对 Agent 分析完全不可用。

系统有两种运行模式：**CLI 模式**（`app.start()` → `app.stop()`，任务完成后自动退出）和 **Server 模式**（启动 FastAPI，持续运行）。`.env` 中 `TRADER_API = "0.0.0.0:8000"` 导致回测也以 Server 模式运行，Agent 无法自动化调用。

## Goals / Non-Goals

**Goals:**
- 每次回测自动输出 JSON 报告文件，Agent 可用 <1KB token 消耗读取完整结果
- 评估指标覆盖业界复合标准：Sharpe、Profit Factor、Max Drawdown、SQN、月度 PnL
- 数据层支持训练/验证/测试三段切分，防止策略过拟合
- 封装可复用 skill，低成本模型（如 Haiku）可独立执行优化循环
- 向后兼容：所有现有策略无需改动即自动获得 JSON 报告

**Non-Goals:**
- 不构建参数网格搜索或 Bayesian 优化框架（那是横向优化，已有）
- 不修改 Backtrader 的实盘 Broker 层（项目已有独立 TraderTask）
- 不引入新的外部依赖
- 不改变现有策略的交易逻辑

## Decisions

### 决策 1：JSON 报告通过自定义 `bt.Analyzer` 实现，而非后处理日志

**选择**：新增 `BacktestReportAnalyzer(bt.Analyzer)`，在 `stop()` 回调中收集数据并写出 JSON。

**备选方案**：
- 解析终端日志提取数据 → 脆弱，耦合日志格式
- 在 `node.py` 的 `cerebro.run()` 后直接调用 `strats[0].analyzers` → 可行但侵入 node.py 过多

**理由**：`bt.Analyzer` 是 Backtrader 的官方扩展点，生命周期由框架管理，`notify_trade()` 回调可精确捕获每笔交易。已有的 `TradeAnalyzer`、`SharpeRatio` 等数据可在 `stop()` 中直接通过 `self.strategy.analyzers` 读取复用，无重复计算。

### 决策 2：Profit Factor 从 `TradeAnalyzer` 数据派生

**选择**：`TradeAnalyzer` 的 `won.pnl.total` / `abs(lost.pnl.total)` 直接计算 Profit Factor。

**理由**：无需新增 analyzer，`TradeAnalyzer` 已经在 Node 中注册且包含所需原始数据（`won.pnl.total`、`lost.pnl.total`）。

### 决策 3：JSON 报告输出路径为 `reports/<strategy>_<symbol>_<interval>_<timestamp>.json`

**选择**：固定目录 `reports/`，文件名包含策略名、标的、周期、时间戳。

**理由**：
- Agent 知道去哪里找报告，无需解析日志
- 时间戳确保历次运行不覆盖，支持对比分析
- 目录可加入 `.gitignore`，不污染代码库

### 决策 4：CLI 模式通过 shell 封装覆盖 `TRADER_API`

**选择**：提供 `scripts/backtest_cli.sh`，内部执行 `TRADER_API="" uv run python -m trader --tasks "$1"`。

**备选方案**：修改 `.env` → 影响所有模式，不安全；新增 CLI 参数 `--no-server` → 需要改动 main.py

**理由**：最小改动，不破坏 Server 模式的现有配置，Agent 调用方式简单清晰。

### 决策 5：数据切分通过多个任务配置文件实现，而非代码层切分

**选择**：`scripts/backtest_train.json`（2023-01~09）、`scripts/backtest_val.json`（2023-10~2024-01）、`scripts/backtest_test.json`（2024 全年）。

**理由**：利用现有任务配置的 `start_time`/`end_time` 参数，无需修改代码；Agent 切换数据集只需切换配置文件；测试集配置存在但 Skill 明确规定优化过程不得使用它。

### 决策 6：Skill 采用严格的 One Change Rule 和明确的停止条件

**选择**：每轮迭代只允许改动一处，改动前记录 git diff，指标退步立即 `git checkout` 还原。

**理由**：多变量同时修改无法判断单个改动的贡献；严格的 One Change Rule 让低成本模型也能正确执行而无需复杂推理。

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|---------|
| `TradeAnalyzer` 在无交易时返回空 autodict，Profit Factor 计算报 KeyError | `BacktestReportAnalyzer.stop()` 中 `getattr` 加默认值 0 |
| 2024 数据下载依赖 Binance API 可用性和 MongoDB 连接 | 提供下载步骤验证，下载失败时退化为 2023 数据的 75/25 切分 |
| per-bar 日志降级为 DEBUG 后，调试策略时信息减少 | 开发者可用 `--log_level DEBUG` 恢复完整日志，行为可配置 |
| JSON 报告文件累积占用磁盘 | `reports/` 加入 `.gitignore`；Skill 指引 Agent 只保留最近 N 次报告 |
| Skill 被低成本模型执行时理解偏差 | Skill 使用明确的检查清单格式，每步有明确的成功/失败判断标准 |

## Migration Plan

1. 新增 `src/trader/analyzers/backtest_report.py`（不影响现有代码）
2. 修改 `node.py` 注册新 Analyzer（单行 `addanalyzer` 调用）
3. 修改 `base_strategy.py` 日志级别（纯文本替换，不影响逻辑）
4. 新增配置文件和脚本（纯新增，无破坏）
5. 新增 Skill 文件（纯新增）
6. 运行一次回测验证 JSON 报告正确生成

**回滚**：所有改动均向后兼容。若需回滚，删除 `BacktestReportAnalyzer` 注册行和 analyzer 文件即可恢复原状。

## Open Questions

- **MongoDB 中是否已有部分 2024 数据**？若有，`auto_download` 会增量补充；若无，首次下载约需几分钟。可在实施时检查。
- **Skill 的目标指标是否需要针对不同策略类型调整**？当前设计为全局默认值（Sharpe > 1.0，Profit Factor > 1.5），趋势跟踪策略可能需要调低胜率要求。Skill 中以注释形式说明。
