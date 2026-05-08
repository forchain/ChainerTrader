## ADDED Requirements

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

