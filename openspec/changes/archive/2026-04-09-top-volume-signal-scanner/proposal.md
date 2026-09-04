## Why

当前仓库已经具备 Binance K 线下载、MongoDB 缓存、Backtrader 策略执行、以及单策略 JSON 报告等基础能力，但缺少一个面向“市场扫描”的统一入口。用户现在想做的不是单个标的回测，而是一个日常可运行的批量扫描脚本：

- 自动选出 Binance 现货 `USDT` 交易对中按成交额排名前 10 的币种
- 排除稳定币交易对，避免 `USDCUSDT`、`FDUSDUSDT` 等挤占榜单
- 先更新数据库，确保所需 K 线窗口完整
- 再只从数据库中读取最近窗口数据执行策略
- 默认运行 `macd_triple_divergence`，并允许后续切换策略
- 仅输出窗口内的 `LONG` / `SHORT` 入场信号，并按信号时间全局排序

如果没有这个入口，用户需要手工挑选标的、分别补数据、分别执行策略，再自行拼接结果，流程重复且容易出错。

## What Changes

- **新增** 批量扫描脚本：统一完成“选币 → 补库 → 读库 → 跑策略 → 汇总信号”
- **新增** Binance Top 10 成交额选币逻辑：仅限现货 `USDT` 交易对，且排除稳定币
- **新增** 数据完整性保障逻辑：在扫描前自动补齐每个 symbol 的 `1d` 与 `1h` 数据窗口
- **新增** 数据库窗口读取逻辑：`1d` 读取最近 1 个月，`1h` 读取最近 1 周
- **新增** 批量信号输出格式：仅记录 `LONG` / `SHORT` 入场信号，并按时间全局排序输出
- **新增** 策略可配置接口：默认 `macd_triple_divergence`，保留切换其他策略的能力

## Capabilities

### New Capabilities

- `top-volume-signal-scanner`：针对 Binance 现货市场的多标的多周期批量信号扫描能力

### Modified Capabilities

- （无现有 spec 需要变更）

## Impact

- **`scripts/`**：新增批量扫描 CLI 脚本
- **`src/trader/exchange/binance/`**：可能补充成交额榜单读取或交易对过滤辅助逻辑
- **`src/trader/database/`**：复用现有 K 线窗口查询能力，不要求修改 DB schema
- **`src/trader/strategy/`**：可能新增信号采集适配层，用于统一抽取 `LONG` / `SHORT` 入场信号
- **兼容性**：向后兼容，不改变现有单策略回测、下载任务、或 Web API 行为

