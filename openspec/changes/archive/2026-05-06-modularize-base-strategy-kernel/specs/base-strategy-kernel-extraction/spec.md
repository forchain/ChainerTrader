## ADDED Requirements

### Requirement: BaseStrategy Delegates Kernel Responsibilities
`BaseStrategy` SHALL act as a Backtrader compatibility shell and strategy hook surface, while signal routing, trade lifecycle, risk computation, and execution orchestration are owned by dedicated framework modules.

#### Scenario: Strategy class remains signal-focused
- **WHEN** a strategy subclass integrates with the framework
- **THEN** the subclass SHALL only need to provide signal conditions, signal context, and optional lifecycle observation hooks
- **THEN** shared trading behavior SHALL be handled by kernel modules rather than strategy subclass overrides

#### Scenario: BaseStrategy delegates shared runtime behavior
- **WHEN** `BaseStrategy.next()` processes a bar
- **THEN** it SHALL delegate signal routing, lifecycle advancement, and risk evaluation to kernel modules
- **THEN** it MUST NOT directly own the mode routing state machine, lifecycle transition state machine, or protective order state machine

### Requirement: Lifecycle Domain Owns Trade State
The framework SHALL define trade context, trade status, trade registry operations, and lifecycle transitions in a dedicated lifecycle/domain module rather than as nested `BaseStrategy` implementation details.

#### Scenario: Entry acceptance transitions through lifecycle module
- **WHEN** an entry confirmation succeeds or an entry execution result is accepted
- **THEN** the lifecycle module SHALL transition the trade state from pending/opening toward active

#### Scenario: Exit completion transitions through lifecycle module
- **WHEN** an exit, stop-loss, or take-profit execution result closes a trade
- **THEN** the lifecycle module SHALL finalize the trade status, exit metadata, and active-trade registry state

#### Scenario: Compatibility aliases are not authoritative
- **WHEN** `BaseStrategy` exposes legacy names such as `TradeStatus` or `TradeContext`
- **THEN** those names SHALL alias or wrap lifecycle-domain types
- **THEN** lifecycle-domain modules SHALL remain the source of truth for status transitions

### Requirement: Risk Engine Owns Protection Decisions
The framework SHALL manage stop-loss, take-profit, OCO-style cancellation, and breakeven replacement decisions in a reusable risk engine that emits normalized risk or execution intents.

#### Scenario: Initial protection emits risk intent
- **WHEN** an entry is filled and the strategy context includes stop-loss or take-profit inputs
- **THEN** the risk engine SHALL emit a protection intent through the configured execution boundary

#### Scenario: Breakeven update emits replacement intent
- **WHEN** breakeven conditions are met for an active trade
- **THEN** the risk engine SHALL emit a protection replacement intent
- **THEN** `BaseStrategy` MUST NOT directly cancel and recreate protective orders for the breakeven move

#### Scenario: Protective order placement is adapter-owned
- **WHEN** a stop-loss or take-profit must be placed in Backtrader
- **THEN** a Backtrader execution adapter SHALL perform the concrete `buy`, `sell`, or `cancel` calls
- **THEN** `BaseStrategy` MUST NOT directly implement protective order placement helpers

### Requirement: Backtrader Adapter Owns Broker-Specific Calls
The framework SHALL isolate Backtrader-specific order APIs behind an adapter so portable kernel modules do not depend on Backtrader strategy inheritance.

#### Scenario: Entry intent is placed through adapter
- **WHEN** the lifecycle or execution orchestrator accepts an entry action in Backtrader mode
- **THEN** the Backtrader adapter SHALL translate it into the required `buy` or `sell` call

#### Scenario: Protection intent is placed through adapter
- **WHEN** the risk engine emits a stop-loss, take-profit, or replacement protection intent in Backtrader mode
- **THEN** the Backtrader adapter SHALL translate it into Backtrader stop, limit, cancel, or OCO-compatible order calls

### Requirement: BaseStrategy Contains No Strategy-Specific Fallbacks
Framework base strategy code SHALL NOT contain strategy-specific parameter checks, strategy names, or strategy-specific report labels.

#### Scenario: MACD triple divergence exit classification is preserved through metadata
- **WHEN** MACD triple divergence triggers a private exit
- **THEN** the strategy or a report adapter SHALL provide the exit classification metadata explicitly
- **THEN** `BaseStrategy` MUST NOT infer MACD-specific labels from `macd_stop_enabled`, strategy names, or hard-coded MACD text

#### Scenario: Structural guard rejects strategy-specific framework leakage
- **WHEN** automated tests inspect `BaseStrategy`
- **THEN** they SHALL fail if strategy-specific identifiers or report strings are embedded in the base framework class
