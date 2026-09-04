## ADDED Requirements

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

