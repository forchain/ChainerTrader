## Why

`scripts/download_backtest_data.py` 每次运行都直接从 Binance API 全量下载 K 线数据到 CSV，即使 MongoDB 中已有完整或部分数据。对于常用的 ETH-USDT 1h 4 年数据（~35,000 根 K 线），每次重复下载需要数分钟和几十次 API 调用，在开发/测试阶段频繁使用时浪费时间和 API 配额。

项目框架内已有完善的 DB 缓存机制（`update_klines_task.py` 的 5 种增量更新情况判断、`backtrader_task.py` 的 `auto_download` 逻辑），但下载脚本完全没有利用这些能力。

## What Changes

- **修改** `scripts/download_backtest_data.py`：增加 DB 优先下载模式
  - 自动从 `.env` 读取 `TRADER_DB` 和 `TRADER_DB_NAME`
  - 有 DB 配置时：检查 DB 已有数据 → 补充下载缺失部分 → 从 DB 导出 CSV
  - DB 连接/操作失败时：打印警告，回退到原有的纯 API 下载逻辑
  - 无 DB 配置时：行为完全不变

## Capabilities

### New Capabilities

- `db-first-download`：DB 优先的 K 线数据下载模式，复用框架已有的增量更新逻辑，避免重复 API 调用

### Modified Capabilities

- （无现有 spec 需要变更）

## Impact

- **`scripts/download_backtest_data.py`**：主要修改文件，新增 DB 读写逻辑和回退机制
- **依赖变更**：脚本新增对 `trader` 包的 import（`DatabaseManager`、`download_range`、`SymbolInterval` 等），运行方式从 `uv run --with requests --with pandas` 变更为需要项目已安装（`make install`）
- **兼容性**：完全向后兼容。无 `TRADER_DB` 环境变量时行为不变；DB 失败时自动回退
