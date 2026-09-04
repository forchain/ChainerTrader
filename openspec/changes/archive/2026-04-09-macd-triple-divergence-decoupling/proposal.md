## Why

当前 `macd_triple_divergence` 策略虽然已经运行在 Chainer 的 `BaseStrategy` 框架上，但策略实现中仍混入了两类不属于“通用策略逻辑”的内容：

- **文档专属交易执行开关**：`doc_trade_logic=True` 用来切换是否采用策略内部硬编码的交易执行方式
- **文档样例元数据**：`DOCUMENTED_CASES_META` 内置了针对 BTC 日线的验证样例

这会带来几个问题：

- 策略信号与框架交易执行边界不清晰
- 策略看起来像绑定了特定文档和特定数据集，而不是可复用于任意标的和任意周期
- 文档专属的验证数据污染了策略本体
- 后续如果要让框架统一管理通用止损/止盈/breakeven，并与策略私有退出规则叠加，会缺少清晰接口

用户希望把三背离策略收敛成一个真正“策略无关标的/周期、框架无关具体文档”的实现：策略负责输出 `LONG` / `SHORT` triggered signals 和策略私有上下文，框架负责统一执行交易；文档样例应作为测试资产存在，而不是策略代码的一部分。

## What Changes

- **修改** `macd_triple_divergence`：去掉 `doc_trade_logic`，统一通过 `get_long_signal()` / `get_short_signal()` 输出信号
- **新增** 策略向框架提供入场上下文的标准接口，例如 `suggested_stop_price` 与 `signal_metadata`
- **保留并规范** 策略私有退出规则：允许像 MACD 次日失败止损这样的策略内部退出逻辑继续存在，并与框架通用止损机制并存
- **移除** 策略内部的 `DOCUMENTED_CASES_META`
- **新增/迁移** 文档样例验证资产到测试层，以 fixture / case 文件或单元测试形式校验 BTC 日线文档样例

## Capabilities

### New Capabilities

- `strategy-signal-context`：策略可向框架提供标准化入场上下文
- `strategy-case-fixtures`：策略文档样例从运行时代码迁移到测试资产

### Modified Capabilities

- `macd-triple-divergence`：从“策略 + 文档交易逻辑 + 内置验证样例”收敛为“通用信号策略 + 可叠加的策略私有退出规则”

## Impact

- **`src/trader/strategy/macd_triple_divergence.py`**：主要修改文件，移除文档耦合逻辑并收敛信号边界
- **`src/trader/strategy/base_strategy.py`**：可能新增策略上下文接口支持
- **`tests/`**：新增或迁移文档样例测试资产
- **兼容性**：会改变三背离策略的内部组织方式，但目标是保持信号检测结果不变

