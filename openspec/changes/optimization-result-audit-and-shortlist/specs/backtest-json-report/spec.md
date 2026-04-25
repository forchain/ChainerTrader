## MODIFIED Requirements

### Requirement: 回测结束后自动输出 JSON 报告文件

每次回测完成后，系统 SHALL 自动将结构化结果写入 `reports/` 目录下的 JSON 文件，文件名格式为 `<strategy>_<symbol>_<interval>_<YYYYMMDD_HHMMSS>.json`。

#### Scenario: 单策略回测完成后生成报告
- **WHEN** 执行一次 BACK_TRADER 任务（任意策略）
- **THEN** 在 `reports/` 目录下生成对应 JSON 文件，文件大小 < 20KB

#### Scenario: JSON 报告包含摘要指标
- **WHEN** JSON 报告文件被读取
- **THEN** `summary` 字段包含：`total_return_pct`、`hold_return_pct`、`sharpe`、`profit_factor`、`sqn`、`max_dd_pct`、`max_dd_days`、`win_rate_pct`、`avg_rr`、`total_trades`、`total_signals`

#### Scenario: JSON 报告包含逐笔交易记录
- **WHEN** JSON 报告文件被读取且存在已完成交易
- **THEN** `trades` 数组中每笔交易包含：`id`、`dir`（L/S）、`entry`（ISO 时间）、`entry_px`、`exit`、`exit_px`、`pnl_pct`、`pnl`、`bars_held`、`exit_reason_code`、`exit_reason_label`、`exit_reason_detail`、`stop_multiple_r`、`risk_reward_ratio`

#### Scenario: 无交易时报告仍然生成
- **WHEN** 回测期间策略未产生任何成交
- **THEN** JSON 报告仍然生成，`trades` 为空数组，`summary.total_trades` 为 0

## ADDED Requirements

### Requirement: 单次回测 JSON 报告必须包含交易行为指纹所需上下文

为了支持后续参数覆盖率审计和行为聚类，单次回测报告 SHALL 包含生成精确交易行为指纹所需的逐笔交易上下文。

#### Scenario: 报告中的交易记录可用于生成行为指纹
- **WHEN** 优化样本报告被读取用于审计或聚类
- **THEN** 系统能够仅基于报告中的逐笔交易字段还原精确执行指纹，而不必重新解析原始日志
