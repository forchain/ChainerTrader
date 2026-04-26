## MODIFIED Requirements

### Requirement: 回测结束后自动输出 JSON 报告文件

每次回测完成后，系统 SHALL 自动将结构化结果写入 `reports/` 目录下的 JSON 文件，文件名格式为 `<strategy>_<symbol>_<interval>_<YYYYMMDD_HHMMSS>.json`。当回测属于 optimization run 时，系统 SHALL 同时生成面向人工验证 workbench 的衍生 JSON 产物，并确保原始单次 run 报告包含 workbench 所需的逐笔证据字段。

#### Scenario: 单策略回测完成后生成报告
- **WHEN** 执行一次 BACK_TRADER 任务（任意策略）
- **THEN** 在 `reports/` 目录下生成对应 JSON 文件，文件大小 < 20KB

#### Scenario: JSON 报告包含摘要指标
- **WHEN** JSON 报告文件被读取
- **THEN** `summary` 字段包含：`total_return_pct`、`hold_return_pct`、`sharpe`、`profit_factor`、`sqn`、`max_dd_pct`、`max_dd_days`、`win_rate_pct`、`avg_rr`、`total_trades`、`total_signals`

#### Scenario: JSON 报告包含逐笔交易记录
- **WHEN** JSON 报告文件被读取且存在已完成交易
- **THEN** `trades` 数组中每笔交易包含：`id`、`dir`（L/S）、`entry`（ISO 时间）、`entry_px`、`exit`、`exit_px`、`pnl_pct`、`bars_held`

#### Scenario: optimization run 的原始报告包含 workbench 证据字段
- **WHEN** 回测报告属于 optimization run 且存在已完成交易
- **THEN** `trades` 数组中每笔交易额外包含信号时间、数量、止损/止盈上下文、退场原因和 workbench 需要的执行证据字段

#### Scenario: 无交易时报告仍然生成
- **WHEN** 回测期间策略未产生任何成交
- **THEN** JSON 报告仍然生成，`trades` 为空数组，`summary.total_trades` 为 0
