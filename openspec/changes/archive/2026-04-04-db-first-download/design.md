## Context

`scripts/download_backtest_data.py` 是一个独立的 CLI 脚本，使用 `requests` + `pandas` 直接调 Binance REST API 下载 K 线数据并保存为 CSV。脚本不依赖 `trader` 包。

项目框架内已有两套 DB 相关逻辑：
- `update_klines_task.py`：`_handle_normal_update()` 实现了 5 种情况的增量更新判断（DB 无数据 / 前缺 / 后缺 / 完整覆盖 / 双向缺），`download_range()` 封装了批量下载 + 重试 + 写 DB
- `backtrader_task.py`：`auto_download` 在 DB 无数据时触发下载，但只判断"空不空"，不处理部分缺失

DB key 格式：`SymbolInterval("ETH-USDT", Interval.INTERVAL_1h).name()` → `"ETHUSDT-1h"`，MongoDB collection 名为 `"klines-ETHUSDT-1h"`。脚本需要将 `ETH-USDT` + `1h` 转换为此格式。

## Goals / Non-Goals

**Goals:**
- 脚本自动检测 `.env` 中的 `TRADER_DB`，有则启用 DB 优先模式
- 复用 `update_klines_task.py` 的 5 种增量判断逻辑，只下载缺失的时间段
- DB 完全覆盖时跳过所有 API 调用，直接导出 CSV
- DB 连接或操作失败时无缝回退到原有纯 API 逻辑
- 导出的 CSV 格式与现有脚本输出完全一致（列名、列顺序、数据类型）

**Non-Goals:**
- 不重构脚本为 trader 框架的 Task 类型
- 不修改 `update_klines_task.py` 或 `backtrader_task.py` 的现有逻辑
- 不新增 CLI 参数（DB 配置从 `.env` 自动读取）

## Decisions

### 决策 1：通过 import trader 包复用逻辑，而非内联 pymongo

**选择**：脚本直接 `from trader.database.manager import DatabaseManager` 等，复用框架已有的所有 DB 和下载逻辑。

**备选方案**：只加 `pymongo`，在脚本内部重新实现 DB 查询/写入逻辑。

**理由**：
- 真正的代码复用，DB 结构或下载逻辑变更时脚本自动跟上
- `download_range()` 已封装了批量下载 + 重试 + 去重 + 写 DB，复制这些逻辑意义不大
- 代价是运行方式变更（需 `make install`），但这是开发/测试工具，开发环境已安装

### 决策 2：DB 配置从 .env 自动读取，不加 CLI 参数

**选择**：用 `python-dotenv` 加载 `.env`，读取 `TRADER_DB` 和 `TRADER_DB_NAME`。有 `TRADER_DB` 就启用 DB 模式，没有就走原逻辑。

**理由**：
- 与项目其他组件（trader CLI、backtrader_task）保持一致的配置方式
- 零额外参数，用户无需改变使用习惯
- 通过环境变量存在与否自动切换模式，最简单的接口

### 决策 3：增量判断复用 `_handle_normal_update` 的 5 种 case 逻辑

**选择**：将 `_handle_normal_update` 的判断逻辑提取为独立函数（或在脚本中重新实现相同的 5 种 case），配合 `download_range()` 补充下载。

**理由**：这 5 种 case 已经覆盖了所有可能的 DB 数据与请求范围的关系。`backtrader_task.py` 的 `auto_download` 只判断"空不空"是一个已知的局限，不应在新功能中重复。

### 决策 4：download_range 是 async 函数，脚本需要适配

**选择**：在脚本中使用 `asyncio.run()` 调用 `download_range()`，并创建必要的 `Event` 和 `Logger` 对象。

**备选方案**：写一个同步包装器 → 增加了不必要的中间层。

**理由**：`download_range()` 内部使用 `await sleep()` 做限流，必须在 async context 中运行。`asyncio.run()` 是最直接的方式。

### 决策 5：回退机制用 try/except 包裹整个 DB 流程

**选择**：整个 DB 优先流程（连接 → 检查 → 下载 → 导出）包裹在 `try/except Exception` 中，捕获后打印警告并调用原有的 `download_klines()` + CSV 保存逻辑。

**理由**：
- DB 失败的原因可能多种多样（网络、权限、数据损坏），逐个捕获不现实
- 对用户来说，最终结果（拿到 CSV）比中间过程重要
- 打印清晰的警告信息让用户知道发生了什么

### 决策 6：DB 导出的 CSV 格式必须与原脚本输出完全一致

**选择**：DB 中 Kline 的字段名（`open_time`, `open`, `high`, `low`, `close`, `volume`, `close_time`, `vol_quote`, `trades`, `vol_taker_base`, `vol_taker_quote`, `ignore`）需要映射为 CSV 的列名（`datetime`, `open`, `high`, `low`, `close`, `volume`, `close_time`, `quote_volume`, `count`, `taker_buy_volume`, `taker_buy_quote_volume`, `ignore`）。

**理由**：下游的 `ImportCSVTask` 和 `BinanceCSVData` 依赖特定的 CSV 格式，不能改变。

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|---------|
| `download_range()` 是 async + 需要 `BinanceExchange` 实例 | 在脚本中初始化 exchange 实例；用 `asyncio.run()` 调用 |
| `download_range()` 需要 `Logger` 和 `Event` 参数 | 创建简单的 Logger 和 Event 实例传入 |
| DB 中 open_time 是秒级 Unix timestamp，CSV 中 datetime 是毫秒级 | 导出时 `open_time * 1000` 转换 |
| 脚本运行方式从 `uv run --with ...` 变为需要 `make install` | 在脚本头部注释中更新使用说明 |
| `BinanceExchange` 初始化可能需要 API key | 检查 `.env` 中的 `TRADER_EXCHANGE` 配置 |

## Migration Plan

1. 修改 `scripts/download_backtest_data.py`，新增 DB 优先逻辑
2. 更新脚本头部的使用说明注释
3. 测试三种场景：DB 完全命中 / DB 部分命中 / DB 不可用回退
4. 验证导出的 CSV 与原脚本输出格式一致

**回滚**：删除 DB 相关代码即可恢复原始脚本。或者用户只需不配置 `TRADER_DB` 环境变量，脚本行为不变。

## Open Questions

- `download_range()` 需要 `BinanceExchange` 实例，而 `BinanceExchange` 的初始化需要哪些参数？需要检查 `.env` 中 `TRADER_EXCHANGE` 的 JSON 结构。如果 exchange 初始化失败，也应该回退到原有逻辑。
- DB 中 `open_time` 存储的是秒级还是毫秒级 timestamp？需要确认以确保 CSV 导出时的单位转换正确。
