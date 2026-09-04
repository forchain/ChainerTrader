## MODIFIED Requirements

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
