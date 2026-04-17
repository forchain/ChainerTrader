## Why

ChainerTrader 目前把 `LONG` / `SHORT` 信号语义、mode 路由和交易生命周期编排主要定义在 `BaseStrategy`，但框架没有提供正式的信号生命周期扩展点，导致策略一旦需要补充信号审计、附加上下文或入场跟踪，就容易通过覆写 `_process_signals()` 复制整段框架流程。这样会把原本应该由框架独占的 mode 路由和状态机规则泄漏到策略层，并在参数优化等批量执行场景中重复暴露同类缺陷。

这次变更的目标是把信号路由 contract 明确收回框架层：策略只负责输出做多/做空信号及其上下文，框架统一负责每根 bar 的信号求值、mode 路由、交易动作选择和生命周期回调，从而避免后续策略继续以本地 override 的方式绕开共享流程。

## What Changes

- 新增框架级 signal routing capability，由 `BaseStrategy` 独占 `LONG_ONLY` / `SHORT_ONLY` / `BOTH` 的信号到动作路由规则
- 新增每根 bar 单次 signal snapshot 机制，让框架和确认流程复用同一份 long/short 信号结果及上下文，避免重复调用信号函数产生副作用
- 新增框架级 signal lifecycle hooks / outcome callbacks，允许策略记录信号审计、entry blocked 原因和入场结果，而不需要覆写 `_process_signals()`
- 调整现有 strategy signal context contract，明确策略通过统一接口提供信号上下文，框架负责消费这些上下文并驱动交易流程
- 新增自动化测试，覆盖 mode 路由归属、per-bar 信号复用、生命周期回调，以及 `LONG_ONLY` 下 short signal 不触发 short entry 的回归场景

## Capabilities

### New Capabilities
- `framework-signal-routing`: 定义框架独占的信号求值、mode 路由、动作选择和信号生命周期扩展点

### Modified Capabilities
- `strategy-signal-context`: 调整信号上下文契约，明确策略通过统一接口提供上下文，且不需要覆写交易路由流程

## Impact

- `src/trader/strategy/base_strategy.py`
- `src/trader/strategy/macd_triple_divergence.py`
- 其他开启 `chainer_auto_signal` 的策略实现
- `tests/`
- `openspec/specs/framework-signal-routing/spec.md`
- `openspec/specs/strategy-signal-context/spec.md`
