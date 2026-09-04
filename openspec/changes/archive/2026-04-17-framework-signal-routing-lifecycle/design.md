## Context

当前 `BaseStrategy` 已经承担了 Chainer 框架的大部分共享交易流程：

`next() -> _process_signals() -> enter_trade()/exit_trade() -> _process_trade_engine()`

其中 mode 语义也已经集中在框架层：
- `LONG_ONLY`: long signal 开多，short signal 平多
- `SHORT_ONLY`: short signal 开空，long signal 平空
- `BOTH`: long/short signal 各自开仓，退出由共享交易引擎处理

但现状仍有两个结构性缺口：
1. 框架没有正式的 signal lifecycle 扩展点，策略如果要记录 signal outcome、blocked reason、entry 跟踪，只能覆写 `_process_signals()`
2. 框架把 `get_long_signal()` / `get_short_signal()` 隐含当作可重复调用的纯函数，但确认流程又会在同一根 bar 内再次调用它们，和“信号生成时顺便附带 metadata / event id”的策略实现存在 contract 冲突

这会导致策略为了扩展审计或上下文而复制整个框架路由逻辑，并把本应只存在于 `BaseStrategy` 的 mode routing 泄漏到策略层。

## Goals / Non-Goals

**Goals:**
- 让 `BaseStrategy` 成为唯一负责 signal routing 的框架入口
- 让框架在每根 bar 内只求值一次 long/short signal，并复用同一份 snapshot 给路由和确认流程
- 为策略提供正式的 signal lifecycle hooks / outcome callbacks，使策略可以记录审计与扩展状态而不需要覆写 `_process_signals()`
- 保持现有 `get_long_signal()` / `get_short_signal()` 与 `get_*_signal_context()` 的主要使用方式向后兼容
- 用自动化测试锁住 framework-owned routing contract，避免后续策略再次局部绕开

**Non-Goals:**
- 不重写现有 enter/exit 交易引擎
- 不改变策略各自的信号检测算法
- 不移除策略私有退出规则或 `notify_order()` 私有跟踪能力
- 不在本次变更中引入新的订单类型或多仓/空仓并发持仓模型

## Decisions

### 决策 1：引入 per-bar Signal Snapshot，由框架缓存一次信号求值结果

**选择**：在 `BaseStrategy` 中引入每根 bar 的 signal snapshot，统一保存：
- `bar_index`
- `long_signal` / `short_signal`
- `long_context` / `short_context`

`_process_signals()` 和 `_process_trade_engine()` 都只消费这份 snapshot，而不再各自直接重复调用 `get_long_signal()` / `get_short_signal()`。

**备选方案**：
- 继续让框架在不同路径上重复调用 signal getter
- 约束所有策略必须把 signal getter 保持为零副作用纯函数

**理由**：后者在现有代码库里并不成立，且策略确实需要在“信号触发当下”挂接结构化上下文。snapshot 可以把“一次信号求值”和“多处流程消费”解耦，同时让 framework routing 与确认流程消费同一份结果。

### 决策 2：`_process_signals()` 保持框架独占，策略通过 hook 扩展而不是 override

**选择**：将 `_process_signals()` 视为框架内部 orchestrator，不再鼓励策略覆写。新增统一的 signal lifecycle hook，使策略可以在以下时机接收结果：
- signal 被检测到
- signal 被 mode / equity / active trade 阻塞
- entry context 被创建或取消
- exit request 被触发

**备选方案**：
- 继续允许策略按需覆写 `_process_signals()`
- 提供多个零散的 `before_enter_trade` / `after_enter_trade` / `on_blocked` hook

**理由**：继续允许 override 等于保留问题根源；而多个零散 hook 会把框架 API 切碎，后续更难演化。一个统一 lifecycle hook 更适合记录审计、信号 outcome 和附加状态。

### 决策 3：signal context contract 继续由策略提供，但由框架在 snapshot 边界统一消费

**选择**：保留 `get_long_signal_context()` / `get_short_signal_context()` 作为策略输出上下文的统一接口，但只在对应 signal 在当前 snapshot 中被触发时读取和缓存，之后都通过 snapshot / trade context 传递。

**备选方案**：
- 直接废弃 `get_*_signal_context()`，要求策略返回更复杂的 signal 对象
- 在每次需要 metadata 时重新调用 `get_*_signal_context()`

**理由**：现有接口已经被使用，直接升级为新对象会扩大迁移面；而重复读取 context 仍会留下同类 contract 不清的问题。按 snapshot 边界消费上下文，可以最小化接口破坏。

### 决策 4：先以 `macd_triple_divergence` 作为迁移样板，再把规则推广到其他自动信号策略

**选择**：先迁移 `macd_triple_divergence`，把其 `_process_signals()` 中的 outcome 记录与 pending entry 跟踪搬到框架 hook / snapshot 机制上，再为其他 `chainer_auto_signal=True` 策略建立统一约束。

**备选方案**：
- 先批量改所有策略
- 只修 `macd_triple_divergence` 当前报错，不建立通用 contract

**理由**：前者风险高、回归面大；后者仍会留下共享 contract 缺口。以当前最复杂、最先暴露问题的策略做迁移样板，能更快验证框架抽象是否够用。

## Risks / Trade-offs

- **Hook 设计过于宽泛，事件语义含糊** → 用稳定的 outcome 类型和测试样例锁定事件名与触发时机
- **Snapshot 生命周期处理不当，出现跨 bar 污染** → snapshot 必须显式绑定 `bar_idx`，每个 `next()` 周期重置
- **现有策略仍继续 override `_process_signals()`** → 在文档与测试中明确 `_process_signals()` 是框架 orchestration 边界，并优先迁移当前已知 override
- **兼容性回归，影响现有纯信号策略** → 保留 `get_long_signal()` / `get_short_signal()` 与 context 接口，新增基准测试覆盖 LONG_ONLY / SHORT_ONLY / BOTH 三种 mode

## Migration Plan

1. 在 `BaseStrategy` 中引入 signal snapshot 与 lifecycle hook，不改变已有外部配置入口
2. 将 `_process_signals()` 与 `_process_trade_engine()` 内部统一切到 snapshot 读取
3. 在 `BaseStrategy` 中固化 framework-owned mode routing contract
4. 迁移 `macd_triple_divergence`，移除其对 `_process_signals()` 的依赖，改用 snapshot/context/hook 机制
5. 补齐框架与策略回归测试，再评估是否需要对其他策略追加迁移任务

**回滚**：如果 snapshot / hook 方案在迁移中暴露不可接受的兼容性问题，可以先保留 snapshot 作为内部缓存实现，延后 hook 暴露；mode routing 仍应保留在 `BaseStrategy`，不回退到策略 override。

## Open Questions

- lifecycle hook 是采用统一 `on_signal_lifecycle_event(...)`，还是使用少量更窄的 protected hook 组合
- 是否需要在框架层显式记录“策略不应覆写 `_process_signals()`”的开发约束，还是只通过 OpenSpec 与测试表达
- snapshot 中是否需要引入独立 dataclass，还是先使用内部字典/轻量对象实现
