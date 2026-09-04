## ADDED Requirements

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
- **THEN** `trades` 数组中每笔交易包含：`id`、`dir`（L/S）、`entry`（ISO 时间）、`entry_px`、`exit`、`exit_px`、`pnl_pct`、`reason`、`bars_held`

#### Scenario: 无交易时报告仍然生成
- **WHEN** 回测期间策略未产生任何成交
- **THEN** JSON 报告仍然生成，`trades` 为空数组，`summary.total_trades` 为 0

---

### Requirement: 策略 per-bar 日志降级为 DEBUG

策略内每根 K 线的例行日志（指标计算、信号检测、信号触发）SHALL 使用 DEBUG 级别，默认运行时不输出；关键事件（开仓成交、平仓成交、止损触发、止盈触发）SHALL 保持 INFO 级别。

#### Scenario: 默认 INFO 日志级别下无 per-bar 噪音
- **WHEN** 以默认 `--log_level INFO` 运行回测
- **THEN** 日志中不出现每根 K 线的「背离检测」「信号触发」字样，只出现开仓/平仓/止损/止盈事件

#### Scenario: DEBUG 级别恢复完整日志
- **WHEN** 以 `--log_level DEBUG` 运行回测
- **THEN** 日志中包含每根 K 线的完整信息，行为与改动前一致

---

### Requirement: Profit Factor 在报告中正确计算

`profit_factor` SHALL 定义为总盈利金额除以总亏损金额绝对值；当无亏损交易时 SHALL 返回 `null`（不除零）。

#### Scenario: 有盈亏交易时计算 Profit Factor
- **WHEN** 回测存在盈利交易和亏损交易
- **THEN** `summary.profit_factor` = 总盈利 PnL / abs(总亏损 PnL)，精确到小数点后两位

#### Scenario: 无亏损交易时 Profit Factor 为 null
- **WHEN** 回测所有交易均盈利（无亏损）
- **THEN** `summary.profit_factor` 为 `null`
