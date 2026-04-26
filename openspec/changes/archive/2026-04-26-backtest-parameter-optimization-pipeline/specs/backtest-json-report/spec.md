## MODIFIED Requirements

### Requirement: 回测结束后自动输出 JSON 报告文件

每次回测完成后，系统 SHALL 自动将结构化结果写入报告目录。普通单次回测继续输出到 `reports/` 目录；参数优化运行 SHALL 输出到 `reports/optimizations/<optimization_run_id>/runs/` 目录下，并在报告中包含参数上下文、运行标识和数据集引用。

#### Scenario: 单策略回测完成后生成报告
- **WHEN** 执行一次 BACK_TRADER 任务（任意策略）
- **THEN** 系统 SHALL 生成对应 JSON 文件
- **AND** 普通单次回测的文件 SHALL 位于 `reports/` 目录
- **AND** 参数优化样本回测的文件 SHALL 位于 `reports/optimizations/<optimization_run_id>/runs/` 目录

#### Scenario: JSON 报告包含摘要指标
- **WHEN** JSON 报告文件被读取
- **THEN** `summary` 字段包含：`total_return_pct`、`hold_return_pct`、`sharpe`、`profit_factor`、`sqn`、`max_dd_pct`、`max_dd_days`、`win_rate_pct`、`avg_rr`、`total_trades`、`total_signals`

#### Scenario: JSON 报告包含逐笔交易记录
- **WHEN** JSON 报告文件被读取且存在已完成交易
- **THEN** `trades` 数组中每笔交易包含：`id`、`dir`（L/S）、`entry`（ISO 时间）、`entry_px`、`exit`、`exit_px`、`pnl_pct`、`reason`、`bars_held`

#### Scenario: 参数化样本报告包含运行与参数上下文
- **WHEN** 参数优化运行中的单次样本报告被读取
- **THEN** 报告 SHALL 包含 `optimization_run_id`
- **AND** SHALL 包含 `report_version`
- **AND** SHALL 包含 `param_id` 和 `params`
- **AND** SHALL 包含 `dataset_ref`

#### Scenario: 无交易时报告仍然生成
- **WHEN** 回测期间策略未产生任何成交
- **THEN** JSON 报告仍然生成，`trades` 为空数组，`summary.total_trades` 为 0
