## 1. 调研与准备

- [x] 1.1 确认 `BinanceExchange` 初始化所需参数：读取 `exchange.py` 构造函数，确认从 `.env` 的 `TRADER_EXCHANGE` JSON 中提取 `api_key`/`api_secret` 的方式
- [x] 1.2 确认 DB 中 `open_time` 的单位（秒 vs 毫秒）：查看 `import_csv_task.py` 中 timestamp 的除法逻辑和 `kline.py` 中的存储方式
- [x] 1.3 确认 `download_range()` 所需的 `Logger` 和 `Event` 最小初始化方式

## 2. 核心实现

- [x] 2.1 在 `download_backtest_data.py` 顶部新增 `try_db_download()` 函数，封装整个 DB 优先流程：
  - 加载 `.env`（`python-dotenv`）
  - 检查 `TRADER_DB` 是否存在
  - 连接 `DatabaseManager`
  - 构建 `SymbolInterval` 对象和 collection name
  - 调用 `get_first_kline()` / `get_latest_kline()` 检查已有范围
- [x] 2.2 实现 5 种增量判断逻辑（复用 `_handle_normal_update` 的 case 结构）：
  - Case 0: DB 无数据 → 全量下载
  - Case 1: end < db_first → 全量下载请求范围
  - Case 2: start < db_first <= end <= db_last → 补前段
  - Case 3: db_first <= start <= end <= db_last → 跳过下载
  - Case 4: start >= db_first and db_last < end → 补后段
  - Case 5: start < db_first and db_last < end → 补前段 + 后段
- [x] 2.3 对需要补充下载的情况，初始化 `BinanceExchange`，通过 `asyncio.run()` 调用 `download_range()`
- [x] 2.4 实现 DB → CSV 导出：`db.kline.get_klines()` → DataFrame，字段映射（`open_time*1000` → `datetime`，`vol_quote` → `quote_volume`，`trades` → `count`，`vol_taker_base` → `taker_buy_volume`，`vol_taker_quote` → `taker_buy_quote_volume`）

## 3. 回退机制

- [x] 3.1 用 `try/except Exception` 包裹整个 `try_db_download()` 调用
- [x] 3.2 捕获异常时打印警告信息（包含异常详情），然后调用原有的 `download_klines()` + CSV 保存逻辑
- [x] 3.3 `TRADER_DB` 不存在时，直接走原有逻辑（不打印警告）

## 4. 主流程集成

- [x] 4.1 重构 `main()` 函数：先尝试 `try_db_download()`，返回成功则结束；返回失败或异常则走原有的 API 下载
- [x] 4.2 更新脚本头部的 docstring 和使用示例，说明新的运行方式（需 `make install`）
- [x] 4.3 保留原有的 `download_klines()` 函数不变，作为回退路径

## 5. 测试验证

- [x] 5.1 测试 DB 完全命中场景：对已在 DB 中的时间范围运行脚本，验证跳过 API 调用、CSV 正确生成
- [x] 5.2 测试 DB 部分命中场景：请求一个超出 DB 已有范围的时间段，验证只补充下载缺失部分
- [x] 5.3 测试 DB 不可用回退场景：临时设置错误的 `TRADER_DB`，验证打印警告后回退到 API 下载
- [x] 5.4 测试无 DB 配置场景：移除 `TRADER_DB` 环境变量，验证行为与原脚本完全一致
- [x] 5.5 对比 DB 导出的 CSV 与原脚本 API 导出的 CSV，验证格式（列名、列顺序、数据类型）一致
