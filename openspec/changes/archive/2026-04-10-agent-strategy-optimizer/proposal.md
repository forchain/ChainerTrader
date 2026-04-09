## Why

ChainerTrader 的回测系统目前输出的是数万行 per-bar 日志（>34MB），没有结构化的逐笔交易记录，无法支持 Agent 进行有效的策略分析和迭代优化。当前基准策略 MACDTripleDivergence 的夏普比率为 -0.53（负数），需要一套系统化的 Agent 驱动工作流来诊断问题并提升策略质量，同时该工作流必须可复用、对低成本模型友好，并为未来迁移到 Binance 实盘做好数据对齐准备。

## What Changes

- **新增** `BacktestReportAnalyzer`：继承 `bt.Analyzer`，每次回测结束后自动输出紧凑 JSON 报告（< 5KB），包含摘要指标、逐笔交易记录、月度 PnL、信号统计
- **新增** `scripts/backtest_cli.sh`：标准化的 CLI 回测命令封装，覆盖 `TRADER_API` 环境变量使回测自动退出，供 Agent 自动化调用
- **新增** `scripts/download_data.json`：用于通过 `auto_download` 机制从 Binance 下载 2024 全年 ETH-USDT 1h 数据
- **新增** `scripts/` 下三个任务配置文件：对应训练集（2023-01~09）、验证集（2023-10~2024-01）、测试集（2024 全年）的回测配置
- **修改** `src/trader/strategy/node.py`：注册 `BacktestReportAnalyzer`，指定报告输出路径
- **修改** `src/trader/strategy/base_strategy.py`：将 per-bar 日志（每根 K 线的指标计算、信号触发）从 `INFO` 降级为 `DEBUG`，只保留关键事件（开仓/平仓/止损/止盈）为 `INFO`
- **新增** `.claude/skills/strategy-optimize.md`：将 Agent 纵向优化工作流封装为可复用 skill，支持任意遵循 ChainerTrader 框架的策略

## Capabilities

### New Capabilities

- `backtest-json-report`：结构化 JSON 回测报告系统，替代原有纯日志输出，为 Agent 分析提供低 Token 消耗的数据入口
- `backtest-data-split`：训练/验证/测试数据集分层管理，包含 2024 数据下载和时间段切分配置，防止策略过拟合
- `agent-optimize-skill`：可复用的 Agent 纵向策略优化工作流 skill，定义问题识别框架、One Change Rule、防过拟合校验和停止条件

### Modified Capabilities

- （无现有 spec 需要变更）

## Impact

- **`src/trader/strategy/node.py`**：新增 analyzer 注册和报告写出逻辑
- **`src/trader/strategy/base_strategy.py`**：日志级别调整（不影响策略逻辑）
- **`src/trader/analyzers/`**：新增目录，存放 `backtest_report.py`
- **`scripts/`**：新增数据下载配置和数据集切分配置文件
- **`.claude/skills/`**：新增 `strategy-optimize.md` skill 文件
- **依赖**：无新增外部依赖（`bt.Analyzer` 为 Backtrader 原生基类，`json` 为标准库）
- **兼容性**：向后兼容，所有现有策略无需修改即可自动获得 JSON 报告输出
