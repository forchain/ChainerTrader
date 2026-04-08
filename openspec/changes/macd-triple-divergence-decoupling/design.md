## Context

`macd_triple_divergence` 当前已经继承 `BaseStrategy`，并使用了 Chainer 的交易引擎能力，例如：

- `get_long_signal()` / `get_short_signal()`
- `enter_trade(...)` / `exit_trade(...)`
- 通用 stop / take profit / breakeven 机制

但它同时又在策略内部加入了以下内容：

- 通过 `doc_trade_logic` 开关决定是否启用“文档版交易执行逻辑”
- 在策略文件内内嵌 `DOCUMENTED_CASES_META`，并把文档样例混入运行期输出

这说明当前实现把三个不同职责放在了一起：

1. **信号检测**
2. **交易执行**
3. **文档样例验证**

本次 change 的目标就是把这三层重新分开。

## Goals / Non-Goals

**Goals:**
- 去掉 `doc_trade_logic`，让信号生成统一落在 `get_long_signal()` / `get_short_signal()`
- 给框架增加“策略提供入场上下文”的标准接口
- 保留策略私有退出规则，并允许它与框架通用机制并存
- 将 `DOCUMENTED_CASES_META` 从策略代码中移出
- 保持三背离信号识别本身不变

**Non-Goals:**
- 不在本次 change 中重新设计所有策略的统一信号协议
- 不修改扫描器 change 的业务范围
- 不要求一次性重构所有现有策略

## Decisions

### 决策 1：移除 `doc_trade_logic`，信号只通过 `get_long_signal()` / `get_short_signal()` 暴露

**选择**：三背离策略不再通过覆写 `_process_signals()` 来分叉“文档交易逻辑”和“框架逻辑”，而是统一输出固定语义的 `LONG` / `SHORT` triggered signals。

**理由**：
- 这符合 Chainer 框架“策略产信号，框架管交易”的边界
- 避免一个策略内部同时维护两套信号处理路径
- 对扫描器等“只关心 triggered signals”的上层功能更友好

### 决策 2：框架增加策略上下文接口，而不是让策略直接改写框架默认止损推导

**选择**：为框架定义一个标准入口，让策略在信号触发时提供上下文，例如：

- `suggested_stop_price`
- `signal_metadata`

框架在入场时可读取这些上下文并应用到交易初始化中。

**理由**：
- 三背离策略的“第三高/第三低点止损”属于信号上下文，而不是通用框架规则
- 通过正式接口传递比在策略里覆写 `_process_signals()` 更清晰

### 决策 3：策略私有退出规则继续允许直接调用 `exit_trade(...)`

**选择**：像 MACD 次日失败止损这种“开仓后动态条件退出”保留在策略内部实现，不强行塞进 `suggested_stop_price` 或框架通用止损参数。

**理由**：
- `suggested_stop_price` 解决的是“入场时初始止损价”
- MACD 次日失败止损是“持仓后的动态退出条件”
- 两者是不同层次的问题，不应混为一谈

### 决策 4：框架通用止损机制与策略私有退出规则可以并存

**选择**：Chainer 的通用 stoploss / take profit / breakeven 继续通过参数开关控制；当这些机制开启时，允许它们与策略私有退出规则同时存在。

**理由**：
- 用户明确要求关闭时只保留文档止损，开启时二者共存
- 架构上这两类机制并不冲突，只需要定义好优先级和状态同步

### 决策 5：文档样例迁移到测试资产，而不是继续内嵌在策略文件中

**选择**：将 `DOCUMENTED_CASES_META` 迁移到 `tests/fixtures/` 或专门的策略案例测试中，由测试驱动验证 BTC 日线文档样例。

**理由**：
- 文档案例属于验证材料，不属于策略运行逻辑
- 三背离策略应该适用于任意标的和任意周期
- 将测试样例外置后，策略代码会更通用、更干净

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|---------|
| 移除 `doc_trade_logic` 后，入场止损初始值不再与文档版逻辑一致 | 先定义明确的 `suggested_stop_price` 接口，再迁移三背离策略 |
| 策略私有退出与框架 stop/tp 同时存在时可能出现重复退出 | 在框架层统一处理订单取消与状态收口，并增加测试覆盖 |
| 移出 `DOCUMENTED_CASES_META` 后丢失现有验证能力 | 在迁移同一轮中补齐 fixture + 测试，确保案例仍可验证 |
| 现有 analyzer/report 依赖文档案例输出 | 将文档案例输出改为测试专用，不再作为通用运行期报告的一部分 |

## Migration Plan

1. 定义策略上下文接口，明确框架如何读取 `suggested_stop_price` 与 `signal_metadata`
2. 重构三背离策略，使其只通过 `get_long_signal()` / `get_short_signal()` 暴露信号
3. 将“第三高/第三低点止损”迁移为通过策略上下文传递的入场信息
4. 保留 MACD 次日失败止损为策略内部 exit rule
5. 移除 `DOCUMENTED_CASES_META` 并将其迁移为测试 fixture / 案例测试
6. 验证三背离信号结果与迁移前一致

## Open Questions

- 策略上下文接口放在 `BaseStrategy` 的哪一层最合适：单独方法、返回对象、还是在 `enter_trade(...)` 增加 override 参数？
- 当策略私有退出和框架 stop order 在同一根 K 线上同时满足时，最终退出原因的归因规则应如何定义？

