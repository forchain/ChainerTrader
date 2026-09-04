## MODIFIED Requirements

### Requirement: 提供三段数据集配置文件

系统 SHALL 提供三个独立的任务配置文件，分别对应训练集、验证集和测试集，通过 `start_time`/`end_time` 参数切分数据时间范围。

#### Scenario: 训练集配置覆盖 2023 年前三季度
- **WHEN** 使用 `configs/tasks/backtests/backtest_train.json` 运行回测
- **THEN** 回测数据范围为 2023-01-01 至 2023-09-30（含）

#### Scenario: 验证集配置覆盖 2023 年第四季度至 2024 年初
- **WHEN** 使用 `configs/tasks/backtests/backtest_val.json` 运行回测
- **THEN** 回测数据范围为 2023-10-01 至 2024-01-31（含）

#### Scenario: 测试集配置覆盖 2024 全年
- **WHEN** 使用 `configs/tasks/backtests/backtest_test.json` 运行回测
- **THEN** 回测数据范围为 2024-01-01 至 2024-12-31（含），数据来源为配置的 SQL 数据库（auto_download）

---

### Requirement: 提供 2024 数据下载配置

系统 SHALL 提供 `configs/tasks/downloads/download_2024_eth.json` 配置文件，利用现有 `auto_download` 机制从 Binance 下载 2024 全年 ETH-USDT 1h 数据并存入配置的 SQL 数据库。

#### Scenario: 执行下载配置后 2024 数据可用
- **WHEN** 执行 `configs/tasks/downloads/download_2024_eth.json` 中的 UPDATE_KLINES 任务
- **THEN** 配置的 SQL 数据库中存在 2024-01-01 至 2024-12-31 的 ETH-USDT 1h K 线数据
