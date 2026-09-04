# strategy-kernel-modularization Specification

## Purpose
TBD - created by archiving change decouple-execution-gateway-and-strategy-kernel. Update Purpose after archive.
## Requirements
### Requirement: Composable Strategy Kernel Modules
The framework SHALL separate strategy runtime responsibilities into composable modules for signal processing, trade lifecycle state transitions, risk computation, and execution orchestration.

#### Scenario: Strategy class remains signal-focused
- **WHEN** a strategy is integrated with the framework
- **THEN** strategy-specific code SHALL only need to provide signal conditions and signal context while shared runtime behavior is handled by kernel modules

### Requirement: Lifecycle State Machine Outside Strategy Implementations
The framework SHALL manage trade lifecycle transitions in a dedicated lifecycle module rather than strategy subclasses.

#### Scenario: Entry to active transition is managed by lifecycle module
- **WHEN** an entry intent is accepted and filled
- **THEN** lifecycle status SHALL transition from opening to active through the lifecycle module without strategy class transition code

### Requirement: Risk Management Module for Stop and Take Profit
The framework SHALL manage stop-loss, take-profit, and breakeven adjustments in a reusable risk module that outputs execution intents.

#### Scenario: Breakeven update emits risk intent
- **WHEN** breakeven conditions are met for an active trade
- **THEN** the risk module SHALL emit a protection replacement intent through the orchestrator

### Requirement: Backward-Compatible Strategy Migration
The framework SHALL provide migration adapters so existing strategies continue to run while responsibilities are progressively moved out of base strategy inheritance.

#### Scenario: Existing strategy runs during phased migration
- **WHEN** a legacy strategy that currently extends the base strategy class is executed
- **THEN** runtime SHALL preserve existing behavior through compatibility adapters during the migration window

