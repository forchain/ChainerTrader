## Context

The current live `TRADER` path runs a strategy over live-updated market data, derives operations, checks exchange balances, and calls `exchange.new_order(...)`. Email notification infrastructure already exists through `--notice`, `NotifyManager`, and mail notify types, but the existing handler is tied to an outdated `tret.operate` shape while current strategy results expose operations through `TraderResult.opts`.

The desired first live workflow is safer than automatic execution: run the strategy locally with configured starting cash/position, maintain local simulated state, and send email recommendations when the local strategy state enters or exits. This avoids depending on untested margin SDK behavior or exact exchange advanced order semantics.

## Goals / Non-Goals

**Goals:**
- Introduce an explicit manual live notification mode for live trader tasks.
- Keep manual mode independent from exchange balance sync and exchange order placement.
- Send email only for locally actionable entry/exit recommendations.
- Include enough operation detail for manual execution: market, strategy, action, side, suggested amount/quantity, signal time/price, local account state, and trigger reason.
- Treat stop-loss and take-profit as local strategy exit triggers and risk reference fields, not as a requirement to place advanced exchange orders.
- Preserve the existing automatic execution behavior unless a future change explicitly revises it.

**Non-Goals:**
- Implement automatic margin/futures/bracket/OCO/stop-limit order placement.
- Confirm real exchange fills, partial fills, order IDs, or externally executed manual trades.
- Add realtime account change listeners or exchange-side reconciliation.
- Guarantee that the user's manual exchange execution matches the local simulated account state.

## Decisions

### Decision 1: Add an execution mode boundary before exchange operations

Manual notification mode should branch before `operate_exchange()` places orders. In manual mode, generated operations are converted into notification events and local simulated state updates; exchange `get_account_balance()` and `new_order()` are not required for notification decisions.

Alternatives considered:
- Reuse automatic `operate_exchange()` and suppress `new_order()`: this keeps too much exchange-account logic in the manual path and would make notifications depend on balances that manual mode explicitly ignores.
- Notify directly from strategies: this duplicates framework routing rules in strategy code and violates the framework-first policy.

### Decision 2: Use local configured state as the source of truth in manual mode

Manual mode should use configured starting capital, configured starting position, and the strategy's local operations to decide when to send entry or exit notifications. The email should clearly state that the operation is a manual-mode recommendation and is not an exchange fill confirmation.

Alternatives considered:
- Sync exchange balances every signal: this is appropriate for future automatic execution, but it defeats the safety-mode goal and reintroduces SDK/account dependencies.
- Maintain only notifications without local state: this would make later exits ambiguous because the system would not know whether its own local strategy considers a position open.

### Decision 3: Keep advanced exchange order semantics out of manual-mode email commands

Entry emails may include suggested stop-loss/take-profit references when the strategy/framework provides them, but the required action remains a simple entry/exit recommendation. Stop-loss or take-profit execution should appear later as a normal local exit notification when the local strategy state triggers it.

Alternatives considered:
- Ask the user to place OCO/bracket/stop-limit orders from the email: these order types vary by exchange, account type, SDK support, precision rules, and margin/futures semantics.

### Decision 4: Format notifications through a structured event before rendering email

Manual notifications should be created from a structured operation event, then rendered as email content. This keeps tests focused on stable fields and allows future channels besides email without changing strategy logic.

Alternatives considered:
- Build email strings inline in `TraderTask`: fast but hard to test and extend.

## Risks / Trade-offs

- Manual local state can diverge from the user's real exchange account if the user ignores or manually adjusts recommendations. -> Email content must label the event as manual-mode/local-state based and include local simulated state.
- Stop-loss/take-profit references might be mistaken for exchange-side protective orders. -> Email wording must distinguish reference fields from submitted orders.
- Existing notify code references `tret.operate`, which no longer matches current result shape. -> Implementation should repair notification extraction around `TraderResult.opts` and cover it with tests.
- Manual mode may still require exchange market data depending on the selected data source. -> Requirements should separate market data availability from account balance/order availability.
