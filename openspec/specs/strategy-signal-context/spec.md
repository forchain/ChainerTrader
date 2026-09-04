# strategy-signal-context Specification

## Purpose
TBD - created by archiving change macd-triple-divergence-decoupling. Update Purpose after archive.
## Requirements
### Requirement: 策略通过统一接口向框架提供入场上下文

系统 SHALL 允许策略在触发 `LONG` / `SHORT` signal 时，通过统一接口向框架提供标准化入场上下文，至少包括 `suggested_stop_price` 和 `signal_metadata`。框架 SHALL 在共享 signal snapshot 边界读取并缓存这些上下文，并通过框架自有的 signal routing 流程消费这些上下文，而不要求策略覆写 `_process_signals()` 或复制 mode routing 逻辑。

#### Scenario: 策略为本次信号提供建议止损价
- **WHEN** 策略产生一个 `LONG` 或 `SHORT` triggered signal
- **THEN** 框架可以读取该信号对应的 `suggested_stop_price` 用于初始化交易止损

#### Scenario: 策略为本次信号提供附加元数据
- **WHEN** 策略产生一个 triggered signal
- **THEN** 框架可以读取 `signal_metadata` 作为结构化上下文，而不需要策略覆写交易流程

#### Scenario: 同一根 bar 内上下文只经统一接口求值一次
- **WHEN** 策略在当前 bar 为 triggered signal 提供上下文
- **THEN** 框架 SHALL 复用该次求值得到的上下文，而不是在后续共享交易流程中再次向策略请求新的上下文副本

---

### Requirement: 策略私有退出规则可以与框架通用止损机制并存

系统 SHALL 允许策略在持仓后根据私有规则通过框架退出入口触发退出，同时保留框架通用 stoploss / take profit / breakeven 机制的可选叠加能力。策略私有退出 SHALL provide structured exit metadata when it needs strategy-specific reporting classification; the framework base class MUST NOT infer private strategy classifications from strategy-specific parameters or hard-coded labels.

#### Scenario: 关闭框架通用止损时仅保留策略私有退出
- **WHEN** 框架通用 stoploss / take profit / breakeven 均关闭
- **THEN** 持仓退出只由策略私有退出规则和必要的最小交易流程控制

#### Scenario: 开启框架通用止损时与策略私有退出共存
- **WHEN** 框架通用 stoploss / take profit / breakeven 开启
- **THEN** 它们 SHALL 与策略私有退出规则同时生效

#### Scenario: 策略私有退出被触发
- **WHEN** 策略内部动态退出条件满足
- **THEN** 策略可以调用框架退出入口完成平仓，并由框架统一处理后续状态收口

#### Scenario: 策略私有退出分类来自元数据
- **WHEN** 策略私有退出需要生成策略专属退出分类或报告文案
- **THEN** 策略 SHALL provide the classification through structured exit metadata or a strategy-specific reporting adapter
- **THEN** framework base strategy code MUST NOT contain strategy-specific classification fallbacks

### Requirement: 三背离策略不依赖文档专属交易执行开关

`macd_triple_divergence` SHALL 通过 `get_long_signal()` / `get_short_signal()` 输出信号，不再依赖 `doc_trade_logic` 这种文档专属交易执行开关。

#### Scenario: 三背离多头信号通过标准入口暴露
- **WHEN** 策略检测到底背离
- **THEN** `get_long_signal()` 返回 `True`

#### Scenario: 三背离空头信号通过标准入口暴露
- **WHEN** 策略检测到顶背离
- **THEN** `get_short_signal()` 返回 `True`

---

### Requirement: 文档样例数据不内嵌在策略运行时代码中

`macd_triple_divergence` SHALL 不在运行时代码中内嵌特定标的、特定周期的文档样例元数据；这些案例 SHALL 迁移到测试或验证资产中。

#### Scenario: 策略运行时不依赖 BTC 日线样例
- **WHEN** 策略在任意标的、任意周期上运行
- **THEN** 策略逻辑不依赖硬编码的 BTC 日线 `DOCUMENTED_CASES_META`

#### Scenario: 文档样例仍可被验证
- **WHEN** 执行对应测试或案例验证
- **THEN** BTC 日线文档样例仍可被读取并用于校验三背离信号行为

### Requirement: Signal Context Feeds Risk and Execution Intents
The framework SHALL propagate strategy-provided signal context, including suggested stop price, signal metadata, trade id, and signal event id, into risk and execution intents without requiring strategy subclasses to know the configured gateway.

#### Scenario: Suggested stop price becomes risk intent input
- **WHEN** a strategy provides `suggested_stop_price` for a routed signal
- **THEN** the framework SHALL make that value available to the risk module when constructing stop-loss protection intents

#### Scenario: Signal metadata remains portable across gateways
- **WHEN** a signal includes structured metadata
- **THEN** backtrader, paper, and live gateway events SHALL preserve that metadata through the normalized execution event model

### Requirement: Strategy Private Exits Use Execution Gateway Boundary
The framework SHALL convert strategy private exit requests into normalized close intents so private exits and framework risk exits share the same downstream execution boundary.

#### Scenario: Private exit is gateway-portable
- **WHEN** a strategy private exit condition calls the framework exit entry point
- **THEN** the framework SHALL produce a normalized close intent that can be executed by the configured gateway

### Requirement: Signal Context Remains Portable Across Kernel Modules
Strategy-provided signal context SHALL flow through signal routing, lifecycle, risk, execution, and reporting boundaries without requiring `BaseStrategy` to inspect strategy-specific fields.

#### Scenario: Suggested stop is consumed by risk module
- **WHEN** a strategy provides `suggested_stop_price` in signal context
- **THEN** the risk module SHALL consume it as stop-loss input through the normalized trade context
- **THEN** `BaseStrategy` MUST NOT compute strategy-specific fallback stops from private metadata fields

#### Scenario: Exit metadata survives lifecycle finalization
- **WHEN** a strategy passes `exit_reason_code`, `exit_reason_label`, or `exit_reason_detail` through the framework exit entry point
- **THEN** lifecycle finalization SHALL preserve that metadata for reports and notifications

