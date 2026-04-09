## ADDED Requirements

### Requirement: 提供三段数据集配置文件

系统 SHALL 提供三个独立的任务配置文件，分别对应训练集、验证集和测试集，通过 `start_time`/`end_time` 参数切分数据时间范围。

#### Scenario: 训练集配置覆盖 2023 年前三季度
- **WHEN** 使用 `scripts/backtest_train.json` 运行回测
- **THEN** 回测数据范围为 2023-01-01 至 2023-09-30（含）

#### Scenario: 验证集配置覆盖 2023 年第四季度至 2024 年初
- **WHEN** 使用 `scripts/backtest_val.json` 运行回测
- **THEN** 回测数据范围为 2023-10-01 至 2024-01-31（含）

#### Scenario: 测试集配置覆盖 2024 全年
- **WHEN** 使用 `scripts/backtest_test.json` 运行回测
- **THEN** 回测数据范围为 2024-01-01 至 2024-12-31（含），数据来源为 MongoDB（auto_download）

---

### Requirement: 提供 2024 数据下载配置

系统 SHALL 提供 `scripts/download_2024_eth.json` 配置文件，利用现有 `auto_download` 机制从 Binance 下载 2024 全年 ETH-USDT 1h 数据并存入 MongoDB。

#### Scenario: 执行下载配置后 2024 数据可用
- **WHEN** 执行 `scripts/download_2024_eth.json` 中的 UPDATE_KLINES 任务
- **THEN** MongoDB 中存在 2024-01-01 至 2024-12-31 的 ETH-USDT 1h K 线数据

---

### Requirement: 提供 CLI 回测命令封装脚本

系统 SHALL 提供 `scripts/backtest_cli.sh` 脚本，覆盖 `TRADER_API` 环境变量为空字符串，确保回测以 CLI 模式运行并在完成后自动退出。

#### Scenario: CLI 脚本执行后自动退出
- **WHEN** 执行 `bash scripts/backtest_cli.sh scripts/backtest_train.json`
- **THEN** 回测完成后进程自动退出，退出码为 0，不启动 Web 服务器

#### Scenario: CLI 脚本接受任意任务配置文件
- **WHEN** 以任意 JSON 配置文件为参数调用 CLI 脚本
- **THEN** 使用该配置文件运行回测
