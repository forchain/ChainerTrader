# framework-signal-routing Specification

## Purpose
定义 Chainer 共享交易框架如何在策略信号与实际交易动作之间进行统一编排，确保 mode 路由、同 bar 信号求值一致性和策略扩展点都由框架层管理，而不是散落在各个策略中。
## Requirements
### Requirement: 框架独占信号 mode 路由
系统 SHALL 由可复用的框架 signal router 统一根据 `chainer_mode`、持仓状态和交易状态，将 `LONG` / `SHORT` 信号路由为开仓、平仓或忽略动作。策略 SHALL 不需要也不应通过覆写共享交易路由流程来重新定义 `LONG_ONLY`、`SHORT_ONLY` 或 `BOTH` 的 mode 语义。`BaseStrategy` SHALL delegate to this router and MUST NOT be the owner of the mode-routing state machine.

#### Scenario: LONG_ONLY 下 short signal 不触发开空
- **WHEN** 某个开启自动信号处理的策略在 `LONG_ONLY` 模式下产生 `SHORT` signal，且当前没有可平的多仓
- **THEN** 框架 MUST 不尝试创建 `SHORT` entry trade

#### Scenario: SHORT_ONLY 下 long signal 不触发开多
- **WHEN** 某个开启自动信号处理的策略在 `SHORT_ONLY` 模式下产生 `LONG` signal，且当前没有可平的空仓
- **THEN** 框架 MUST 不尝试创建 `LONG` entry trade

#### Scenario: BOTH 下双向信号沿共享入口路由
- **WHEN** 某个开启自动信号处理的策略在 `BOTH` 模式下产生 `LONG` 或 `SHORT` signal
- **THEN** 框架 SHALL 通过共享交易入口按各自方向创建对应 entry context

#### Scenario: Router returns framework actions
- **WHEN** signal router accepts or blocks a signal
- **THEN** it SHALL return a framework action or lifecycle event payload for the strategy kernel to consume
- **THEN** it MUST NOT directly call broker, paper, or live exchange APIs

### Requirement: 框架在同一根 bar 内复用单次信号求值结果
系统 SHALL 在每根 bar 内只求值一次 long/short signal 及其上下文，并在 signal routing、pending entry confirmation 和其他共享交易流程中复用同一份 signal snapshot。

#### Scenario: 确认流程读取同一份 opposing signal 结果
- **WHEN** 某个待确认 entry 在当前 bar 需要判断是否出现 opposing signal
- **THEN** 框架 MUST 使用该 bar 已缓存的 signal snapshot，而不是再次直接调用策略 signal getter

#### Scenario: 同一根 bar 的信号上下文保持一致
- **WHEN** 某个策略在当前 bar 触发 signal 并提供 `suggested_stop_price` 或其他 signal metadata
- **THEN** 后续共享交易流程读取到的上下文 MUST 与该 bar 首次信号求值时缓存的内容一致

---

### Requirement: 框架向策略暴露信号生命周期扩展点
系统 SHALL 提供框架级 signal lifecycle 扩展点，使策略可以观察信号被检测、被阻塞、创建 entry context、取消 entry context 或触发 exit request 的结果，而不需要覆写共享 signal routing 流程。

#### Scenario: signal 被模式规则阻塞时可被观察
- **WHEN** 某个 signal 因 `chainer_mode` 规则而未被路由为 entry action
- **THEN** 框架 SHALL 允许策略通过信号生命周期扩展点接收到该阻塞结果及原因

#### Scenario: entry context 创建结果可被观察
- **WHEN** 某个 signal 成功创建 entry context 或在创建后立刻被取消
- **THEN** 框架 SHALL 允许策略通过信号生命周期扩展点接收到对应 outcome 及关联上下文

### Requirement: 信号生命周期结果可供通知流程消费

系统 SHALL 允许框架管理的信号生命周期结果被任务层或通知层消费，用于生成进场、出场、阻塞或取消等用户可见事件，而不要求具体策略覆写共享信号路由流程。

#### Scenario: entry context 创建后可生成通知事件
- **WHEN** 框架根据信号成功创建 entry context
- **THEN** 任务层或通知层 SHALL 能读取方向、信号上下文、trade id 和本地交易状态以生成进场通知事件

#### Scenario: exit request 触发后可生成通知事件
- **WHEN** 框架根据信号或本地交易引擎触发 exit request
- **THEN** 任务层或通知层 SHALL 能读取方向、信号上下文和退出原因以生成出场通知事件

#### Scenario: 通知消费不改变策略路由职责
- **WHEN** 系统启用手动实盘通知模式
- **THEN** 策略 SHALL 继续通过标准信号接口和框架 lifecycle 机制暴露行为
- **THEN** 策略 MUST NOT 为了发送通知而覆写共享 `_process_signals()` 路由流程

### Requirement: Signal Routing Emits Execution Intents
The framework signal routing flow SHALL convert routed trade actions into normalized execution intents before they reach broker, paper, or live exchange execution.

#### Scenario: Routed entry becomes execution intent
- **WHEN** framework signal routing accepts a long or short entry signal
- **THEN** the framework SHALL create a normalized entry execution intent instead of directly invoking a concrete broker or exchange API

#### Scenario: Routed exit becomes execution intent
- **WHEN** framework signal routing accepts an exit signal or framework-managed close action
- **THEN** the framework SHALL create a normalized close execution intent with trade context metadata

### Requirement: Signal Routing Preserves Existing Mode Semantics
The framework SHALL preserve existing `LONG_ONLY`, `SHORT_ONLY`, and `BOTH` mode routing behavior while changing the downstream execution boundary to the execution gateway contract.

#### Scenario: Mode routing remains unchanged after gateway integration
- **WHEN** a strategy signal is blocked or accepted by existing mode rules
- **THEN** the same block or accept result SHALL occur regardless of the configured execution gateway

### Requirement: Signal Router Is Independently Testable
The framework SHALL expose signal routing behavior as a testable module independent of `BaseStrategy` inheritance.

#### Scenario: Mode routing can be tested without Backtrader strategy instance
- **WHEN** tests provide a signal snapshot, mode, and lifecycle state to the signal router
- **THEN** the router SHALL return the same accept, block, entry, or exit decisions that the Backtrader runtime uses

#### Scenario: BaseStrategy uses router output
- **WHEN** `BaseStrategy` processes signals for a bar
- **THEN** it SHALL consume router output instead of embedding mode-specific routing branches inline

