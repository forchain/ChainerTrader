## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Signal Router Is Independently Testable
The framework SHALL expose signal routing behavior as a testable module independent of `BaseStrategy` inheritance.

#### Scenario: Mode routing can be tested without Backtrader strategy instance
- **WHEN** tests provide a signal snapshot, mode, and lifecycle state to the signal router
- **THEN** the router SHALL return the same accept, block, entry, or exit decisions that the Backtrader runtime uses

#### Scenario: BaseStrategy uses router output
- **WHEN** `BaseStrategy` processes signals for a bar
- **THEN** it SHALL consume router output instead of embedding mode-specific routing branches inline
