## Why

Live strategy operation needs a safer first step before automatic exchange execution. The system should be able to run a strategy against live-updated market data, maintain a local simulated account from configured starting capital/position, and email actionable entry/exit recommendations without depending on exchange account balance sync, margin order support, or order placement SDK behavior.

## What Changes

- Add a manual live notification mode for live trader tasks.
- In manual mode, the system SHALL not call exchange order APIs and SHALL not require exchange balance sync to decide whether to notify.
- Manual mode SHALL use configured local starting capital and position to advance strategy state.
- When the local strategy state produces an entry or exit operation, the system SHALL send an email notification.
- Notification content SHALL include market, strategy, entry/exit action, side, suggested amount/quantity, signal price/time, local simulated account state, and trigger reason when available.
- Stop-loss and take-profit SHALL be treated as strategy risk references and/or later local exit triggers, not as a requirement to place advanced exchange orders in the first version.
- Automatic exchange execution remains out of scope for this change and can be introduced later as a separate mode.

## Capabilities

### New Capabilities
- `manual-live-trade-notifications`: Defines manual live notification mode, local simulated account behavior, and email content for entry/exit recommendations.

### Modified Capabilities
- `framework-signal-routing`: Clarify that framework-managed entry/exit lifecycle information can be consumed by notification flows without changing strategy-local signal generation.

## Impact

- Affected code areas:
  - `src/trader/task/trader_task.py`
  - `src/trader/notify/`
  - `src/trader/strategy/trader_result.py`
  - task/config parsing for live execution mode and local starting state
  - tests covering manual notification behavior and no exchange order placement
- Runtime behavior:
  - Manual mode requires market data and notification configuration.
  - Manual mode does not require margin order support or successful exchange order placement.
  - Automatic exchange execution behavior should remain unchanged unless explicitly selected by a future mode.
