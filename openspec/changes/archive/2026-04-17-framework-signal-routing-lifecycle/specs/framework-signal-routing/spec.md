## ADDED Requirements

### Requirement: 框架独占信号 mode 路由
系统 SHALL 由框架统一根据 `chainer_mode`、持仓状态和交易状态，将 `LONG` / `SHORT` 信号路由为开仓、平仓或忽略动作。策略 SHALL 不需要也不应通过覆写共享交易路由流程来重新定义 `LONG_ONLY`、`SHORT_ONLY` 或 `BOTH` 的 mode 语义。

#### Scenario: LONG_ONLY 下 short signal 不触发开空
- **WHEN** 某个开启自动信号处理的策略在 `LONG_ONLY` 模式下产生 `SHORT` signal，且当前没有可平的多仓
- **THEN** 框架 MUST 不尝试创建 `SHORT` entry trade

#### Scenario: SHORT_ONLY 下 long signal 不触发开多
- **WHEN** 某个开启自动信号处理的策略在 `SHORT_ONLY` 模式下产生 `LONG` signal，且当前没有可平的空仓
- **THEN** 框架 MUST 不尝试创建 `LONG` entry trade

#### Scenario: BOTH 下双向信号沿共享入口路由
- **WHEN** 某个开启自动信号处理的策略在 `BOTH` 模式下产生 `LONG` 或 `SHORT` signal
- **THEN** 框架 SHALL 通过共享交易入口按各自方向创建对应 entry context

### Requirement: 框架在同一根 bar 内复用单次信号求值结果
系统 SHALL 在每根 bar 内只求值一次 long/short signal 及其上下文，并在 signal routing、pending entry confirmation 和其他共享交易流程中复用同一份 signal snapshot。

#### Scenario: 确认流程读取同一份 opposing signal 结果
- **WHEN** 某个待确认 entry 在当前 bar 需要判断是否出现 opposing signal
- **THEN** 框架 MUST 使用该 bar 已缓存的 signal snapshot，而不是再次直接调用策略 signal getter

#### Scenario: 同一根 bar 的信号上下文保持一致
- **WHEN** 某个策略在当前 bar 触发 signal 并提供 `suggested_stop_price` 或其他 signal metadata
- **THEN** 后续共享交易流程读取到的上下文 MUST 与该 bar 首次信号求值时缓存的内容一致

### Requirement: 框架向策略暴露信号生命周期扩展点
系统 SHALL 提供框架级 signal lifecycle 扩展点，使策略可以观察信号被检测、被阻塞、创建 entry context、取消 entry context 或触发 exit request 的结果，而不需要覆写共享 signal routing 流程。

#### Scenario: signal 被模式规则阻塞时可被观察
- **WHEN** 某个 signal 因 `chainer_mode` 规则而未被路由为 entry action
- **THEN** 框架 SHALL 允许策略通过信号生命周期扩展点接收到该阻塞结果及原因

#### Scenario: entry context 创建结果可被观察
- **WHEN** 某个 signal 成功创建 entry context 或在创建后立刻被取消
- **THEN** 框架 SHALL 允许策略通过信号生命周期扩展点接收到对应 outcome 及关联上下文
