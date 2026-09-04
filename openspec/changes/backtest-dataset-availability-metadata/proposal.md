## Why

当前历史数据补数默认按 `start_time -> end_time` 正向推进，这在长区间回测和参数优化场景下会产生明显浪费：
- 当请求区间早于交易对真实可交易时间时，系统会反复请求上市前根本不存在的数据窗口
- 当数据库只保存了局部历史时，系统缺少一个独立的“最早已知可用时间”元数据，无法区分“本地还没拉全”和“交易所根本没有”
- 这些无效补数会放大 Binance API 不稳定、Mongo 写入延迟和长区间回测启动时间，尤其在 `1d` 长窗口上最明显

现在需要把“历史覆盖边界”从临时推导逻辑提升为显式元数据：让系统在正常历史回补过程中，从后往前拉取数据并持续学习 `(exchange, symbol, interval)` 的 `earliest_known_open_time`，以后优先利用这个边界减少无效下载，同时保留对上市后真实中间缺口的修复能力。

## What Changes

- 为 `(exchange, symbol, interval)` 引入 availability metadata，持久化 `earliest_known_open_time`
- 将历史补数策略从“默认正向回补”升级为“按请求结束时间向前回补，并在过程中学习更早边界”
- 区分 `EMPTY` 与 `ERROR` 语义：请求成功但空数据才允许停止当前回补；网络错误/超时不能被当成“已到最早边界”
- 让 `DatasetResolver` 使用 availability metadata 作为优化边界，而不是直接信任数据库首根 K 线
- 保持上市后真实中间缺口的检测与补数逻辑不变
- 为倒序补数状态机和 metadata 单调更新补充自动化测试，默认采用 TDD

## Capabilities

### New Capabilities
- `backtest-dataset-availability`: 为历史回测数据准备维护交易对/周期级的最早已知可用时间元数据，并在回补过程中持续向更早更新

### Modified Capabilities
- `backtest-data-split`: 数据准备阶段将不再默认从请求起点正向穷举，而是结合 availability metadata 与倒序回补策略组织历史覆盖

## Impact

- `src/trader/task/dataset_resolver.py`
- `src/trader/task/update_klines_task.py`
- `src/trader/database/`
- `src/trader/exchange/binance/exchange.py`
- `tests/`
