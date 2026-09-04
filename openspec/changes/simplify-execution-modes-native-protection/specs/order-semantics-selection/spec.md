## ADDED Requirements

### Requirement: Order selection follows strategy semantics
The system SHALL select the simplest order behavior that satisfies the strategy or framework semantics. Advanced exchange order types MUST NOT be required for ordinary entry or close behavior, and ordinary orders MUST NOT be used as substitutes when the configured semantics require stop-loss, stop replacement, or stop/take-profit mutual cancellation behavior.

#### Scenario: Market entry uses ordinary order semantics
- **WHEN** a strategy requests a live automatic entry without stop-loss or take-profit protection in the same execution intent
- **THEN** the system SHALL submit an ordinary market entry order through the configured live gateway
- **THEN** the system MUST NOT require bracket, OCO, stop-limit, or take-profit order support for that entry

#### Scenario: Market close uses ordinary order semantics
- **WHEN** a strategy requests a live automatic close without conditional trigger semantics
- **THEN** the system SHALL submit an ordinary close order through the configured live gateway
- **THEN** the system MUST NOT require advanced order support for that close

#### Scenario: Stop-loss requires protection semantics
- **WHEN** the Chainer framework or strategy context provides a stop-loss value for an automatically executed live position
- **THEN** the system SHALL represent that value as native live protection semantics
- **THEN** the system MUST NOT replace the stop-loss with a later ordinary market or limit order submitted only after a closed-candle strategy check

#### Scenario: Stop and take-profit require mutual cancellation when configured together
- **WHEN** an automatically executed live position has both stop-loss and take-profit protection values
- **THEN** the system SHALL use native OCO-style, bracket-style, or gateway-equivalent mutual cancellation semantics when the selected live gateway supports them
- **THEN** the system MUST reject or fail the protection intent explicitly when the selected live gateway cannot satisfy the mutual cancellation requirement

### Requirement: Backtrader validates portable protection semantics
Backtrader SHALL be the project test/backtest execution engine for portable strategy behavior, including market entry, market close, stop-loss, take-profit, stop/take-profit mutual cancellation, and breakeven stop replacement within the available input data granularity.

#### Scenario: Backtrader receives a protected entry
- **WHEN** a backtest entry intent includes stop-loss and take-profit values
- **THEN** the Backtrader execution path SHALL submit broker-native stop and take-profit behavior for the active position
- **THEN** the Backtrader execution path SHALL preserve role metadata needed to classify entry, stop exit, take-profit exit, and ordinary close events

#### Scenario: Backtrader data granularity is explicit
- **WHEN** a stop-loss or take-profit is triggered during a Backtrader run
- **THEN** the result SHALL be interpreted according to Backtrader execution semantics and the available OHLC or tick data granularity
- **THEN** the system MUST NOT claim tick-accurate ordering when the input data does not provide tick-level ordering

### Requirement: Native live protection is verified before being reported as armed
The live execution gateway SHALL report protection as armed only after the selected exchange-native protection order or order set has been accepted and enough exchange identifiers have been captured for reconciliation.

#### Scenario: Native protection is accepted
- **WHEN** the live gateway submits stop-loss, take-profit, or stop/take-profit protection and the exchange returns accepted native order identifiers
- **THEN** the system SHALL emit a `protection_armed` execution event
- **THEN** the system SHALL persist the protection order identifiers and role metadata needed for restart recovery

#### Scenario: Native protection cannot be verified
- **WHEN** the exchange response does not provide verifiable native protection order identifiers
- **THEN** the system MUST NOT emit `protection_armed`
- **THEN** the system SHALL emit or persist a protection-missing or protection-failed result with the concrete reason
