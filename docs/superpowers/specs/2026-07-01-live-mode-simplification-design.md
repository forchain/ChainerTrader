# Live Mode Simplification Design

## Status
Approved for implementation by user instruction.

## Date
2026-07-01

## Context
Live task configuration currently has two independent-looking switches:

- `live_data_mode`: `polling` or `realtime`
- `live_execution_mode`: `manual_notify`, `small_live_auto`, `full_live_auto`, or `auto_trade`

The names imply two different market-data mechanisms and several different execution products. The implementation does not match that mental model.

`live_data_mode=realtime` starts the persistent Backtrader live runner, but the market stream is still driven by the CCXT polling scheduler. It is not a true push-data implementation. `live_data_mode=polling` starts a legacy live loop that repeatedly reloads a fresh K-line window and reruns the strategy, which can re-detect old signals unless each strategy or downstream path suppresses them.

`live_execution_mode` also carries historical staging labels. The product direction is now simpler: live tasks either notify only or submit real orders. Order size and risk controls should be configured by amount fields and execution safeguards, not by extra mode names.

## Goal
Reduce live task configuration and runtime behavior to one execution switch:

- `manual_notify`: run the live strategy runtime and emit notifications/dashboard events without exchange orders
- `auto_trade`: run the same live strategy runtime and route eligible strategy operations to live order execution

Remove `live_data_mode` as a public configuration field and delete the legacy polling live runtime path.

Reject old execution modes instead of silently translating them when users provide external configs. Repository-owned sample configs should be migrated to the new schema in the same change.

## Non-Goals
- Implementing WebSocket or push-based market data.
- Changing strategy signal generation rules.
- Adding a new data-source abstraction.
- Keeping a compatibility layer for removed live modes.
- Preserving the legacy window-rerun live polling path behind a hidden flag.

## Recommended Approach
Perform a hard simplification in the shared framework layer.

`TaskConfig` should no longer accept, store, serialize, or expose `live_data_mode`. `parse_task_config()` should reject configs that include the removed field with a clear error telling the operator to delete it. `TraderTask.start()` should always start the persistent live runner for `TRADER` live execution instead of branching on a data mode.

`normalize_live_execution_mode()` should support only `manual_notify` and `auto_trade`. Removed values such as `small_live_auto`, `full_live_auto`, `staged_auto_trade`, `paper_auto`, and shorthand aliases should fail during config parsing. This makes stale external configs visible immediately.

Repository configs under `configs/tasks` should be updated so:

- every `live_data_mode` entry is removed
- every `small_live_auto` and `full_live_auto` entry becomes `auto_trade`
- no active repository config contains `staged_auto_trade`, `paper_auto`, or other removed live execution modes
- existing `manual_notify` entries remain `manual_notify`
- repository-owned sample config filenames that encode removed modes or data modes are renamed or deleted

Examples that must not remain as active sample config names after this change include:

- `configs/tasks/live/small_live_auto_btc_1m.json`
- `configs/tasks/live/full_live_auto_btc_1m.json`
- `configs/tasks/live/realtime_macd_triple_divergence_top10_production.json`

Replacement names:

- `configs/tasks/live/auto_trade_capped_btc_1m.json`
- `configs/tasks/live/auto_trade_btc_1m.json`
- `configs/tasks/live/auto_trade_macd_triple_divergence_top10_production.json`

The web task form should expose only `manual_notify` and `auto_trade` for live execution mode and should remove the data mode selector.

## Persisted Task State Migration
The implementation must not keep a recovery-only compatibility branch that silently understands removed modes forever.

Persisted task state created by older versions still matters because restart recovery can reparse stored task config JSON. The rollout should handle that state explicitly before the new parser rejects legacy fields:

- provide a one-shot migration or maintenance command that rewrites persisted task config JSON to the new schema
- remove `live_data_mode` from persisted task config JSON
- rewrite persisted `small_live_auto` and `full_live_auto` execution modes to `auto_trade`
- leave persisted `manual_notify` execution mode unchanged
- reject `staged_auto_trade`, `paper_auto`, aliases such as `manual` / `notify`, and any other unsupported mode during migration

If a deployment does not run that migration, the deployment precondition is that no persisted live task config contains `live_data_mode` or a removed `live_execution_mode` value, including `RUNNING` tasks eligible for recovery.

After migration, recovery should parse only the new schema. If recovery finds an unmigrated legacy value, it should fail loudly with the same parser error instead of falling back to legacy runtime behavior.

## Execution Semantics
Both supported modes use the same live market runtime:

1. load startup warmup candles
2. create one persistent Backtrader live runner
3. advance that runner with each newly closed K-line from the current CCXT polling scheduler
4. keep open candles dashboard-only when available

The difference is only execution routing:

- `manual_notify` records and publishes strategy operations as notifications/manual actions; it does not place exchange orders
- `auto_trade` routes eligible strategy operations through the live execution router

The old `polling` loop that repeatedly downloads a full K-line window and reruns the strategy should be deleted from `TraderTask`. Any remaining helper code that becomes unused as a result should be removed in the same change.

## Auto Trade Sizing
The removed execution labels must not carry sizing semantics anymore. `auto_trade` has one authoritative sizing contract across fresh startup, order routing, and recovery budget reconstruction.

For an `auto_trade` task:

- `strategy_cash` is `free` when `free > 0`, otherwise global configured cash
- `order_notional_cap` is `live_trade_max_notional` when configured with a positive value, otherwise unlimited
- `effective_live_budget` is `min(strategy_cash, order_notional_cap)` when a positive order cap exists, otherwise `strategy_cash`
- Backtrader strategy simulation uses `strategy_cash`
- fresh startup balance preflight uses `effective_live_budget`
- recovered runtime budget reconstruction uses `effective_live_budget`
- order routing must never submit an entry order whose notional exceeds positive `order_notional_cap`

This preserves small-order safety as an explicit numeric cap while removing `small_live_auto` as a mode. Migrating a repository config from `small_live_auto` to `auto_trade` must preserve its `live_trade_max_notional` value.

## Error Handling
Config parsing should fail fast when it sees removed fields or modes.

Required errors:

- `live_data_mode is no longer supported; remove it from the task config`
- `unsupported live_execution_mode: small_live_auto`
- `unsupported live_execution_mode: full_live_auto`
- `unsupported live_execution_mode: staged_auto_trade`

The exact messages can follow existing project style, but they must identify the bad field or value directly.

The recovery key should drop `live_data_mode`. Config serialization should no longer emit the field. Runtime status and dashboard payloads should continue to expose the execution mode as `manual_notify` or `auto_trade`.

## Documentation And UI
README and user-facing task documentation should describe one live runtime and two execution modes.

Docs should avoid describing the persistent live runner as a true data push implementation. The accurate wording is that the live runner receives newly closed candles from the current CCXT polling scheduler.

The task creation UI should remove the data mode field and present execution options using the two supported values. Existing frontend form defaults should use `auto_trade` only where an automated order mode is intended.

## Superseded Specs And Docs
The implementation change must update or explicitly mark obsolete any repository spec that still describes removed modes or `live_data_mode` as current behavior.

This applies to active user-facing docs, OpenSpec specs, acceptance contracts, checklists, plans, runbooks, and operational verification docs. Historical artifacts may remain only when they are clearly marked non-authoritative/historical and are not linked as current usage guidance.

At minimum, the implementation should inspect and update or obsolete:

- `openspec/specs/staged-live-auto-execution/spec.md`
- `openspec/specs/live-auto-order-safety/spec.md`
- `openspec/specs/live-cross-margin-short-execution/spec.md`
- `openspec/specs/manual-live-trade-notifications/spec.md`
- active `openspec/changes/**` artifacts
- `docs/superpowers/specs/2026-06-10-live-task-restart-recovery-design.md`
- `docs/superpowers/specs/2026-06-17-task-fund-reservation-design.md`
- `docs/superpowers/specs/2026-07-01-live-task-balance-preflight-design.md`
- `docs/superpowers/specs/integrated-acceptance-testing-plan.md`
- active `docs/acceptance/**/acceptance-contract.md` files
- README sections that describe live mode configuration or production task paths

Those documents should no longer require `small_live_auto`, `full_live_auto`, `staged_auto_trade`, `paper_auto`, or `live_data_mode` as live configuration semantics after this change lands.

The implementation should include a repository-wide search for `live_data_mode`, `small_live_auto`, `full_live_auto`, `staged_auto_trade`, `paper_auto`, and active sample filenames containing `realtime_` where the name means the removed data mode. Remaining matches must be either code that rejects legacy input, tests that assert rejection/migration, or explicitly historical documentation.

## Testing
Automated coverage should prove:

- config parsing rejects any `live_data_mode` field
- config parsing rejects `small_live_auto`, `full_live_auto`, `staged_auto_trade`, and `paper_auto`
- config parsing accepts only `manual_notify` and `auto_trade`
- serialized task configs no longer include `live_data_mode`
- live `TRADER` tasks start the persistent live runner without consulting data mode
- manual notify still does not place exchange orders
- auto trade still routes eligible operations to the execution router
- task recovery identity no longer includes `live_data_mode`
- repository sample configs parse after migration
- UI task field definitions no longer expose the data mode selector or removed execution modes
- persisted task config migration removes legacy fields and rewrites supported old auto modes
- recovery fails loudly if it encounters unmigrated legacy config after migration
- active repository docs and sample config filenames do not present removed modes as supported current usage

Tests that currently encode `realtime` as a config mode should be updated to assert the persistent live runner behavior without requiring a config field.

## Rollout Notes
This is an intentionally breaking configuration cleanup. Operators with external task files must remove `live_data_mode` and replace old auto execution labels with `auto_trade`.

The repository-owned sample configs are migrated in the implementation change so current examples remain usable. External stale configs fail loudly instead of receiving silent compatibility behavior.
