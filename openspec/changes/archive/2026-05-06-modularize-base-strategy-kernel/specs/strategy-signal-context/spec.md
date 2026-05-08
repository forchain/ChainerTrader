## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Signal Context Remains Portable Across Kernel Modules
Strategy-provided signal context SHALL flow through signal routing, lifecycle, risk, execution, and reporting boundaries without requiring `BaseStrategy` to inspect strategy-specific fields.

#### Scenario: Suggested stop is consumed by risk module
- **WHEN** a strategy provides `suggested_stop_price` in signal context
- **THEN** the risk module SHALL consume it as stop-loss input through the normalized trade context
- **THEN** `BaseStrategy` MUST NOT compute strategy-specific fallback stops from private metadata fields

#### Scenario: Exit metadata survives lifecycle finalization
- **WHEN** a strategy passes `exit_reason_code`, `exit_reason_label`, or `exit_reason_detail` through the framework exit entry point
- **THEN** lifecycle finalization SHALL preserve that metadata for reports and notifications
