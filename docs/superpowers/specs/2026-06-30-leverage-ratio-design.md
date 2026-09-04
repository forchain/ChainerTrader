# Leverage Ratio Configuration Design

## Status
Approved for implementation by user instruction.

## Date
2026-06-30

## Context
ChainerTrader started as a spot-only system. The next step is to support leveraged execution paths, including future futures support, primarily to enable short trading without letting operators unknowingly take on excessive borrowing risk.

The current project already has a separate sizing concept for each operation. That existing sizing control must remain independent. This change introduces a different control: a global leverage ratio that caps how much nominal exposure leveraged execution may use relative to available capital.

The user intent is conservative:

- default leverage ratio is `1.0`
- the configuration is global, not per-task
- the configuration is read from environment variables, matching the current `.env`-based setup
- it applies only to leveraged / futures execution paths
- spot execution must not be affected
- the system should absorb normal execution friction internally, including fee and slippage effects
- invalid values must fail fast at startup instead of silently falling back

## Goal
Add a global leverage ratio configuration that constrains leveraged and futures execution to a 1:1 default ceiling, with explicit validation and clear separation from existing task sizing controls.

## Non-Goals
- Changing the meaning of the existing single-operation capital sizing parameter.
- Introducing per-strategy or per-task leverage overrides.
- Adding a new CLI flag for leverage ratio.
- Changing spot execution semantics.
- Building the full futures risk engine, liquidation model, or maintenance-margin logic in this change.

## Recommended Approach
Add a single global config field, `leverage_ratio`, on the shared runtime config object and expose it through `.env` as `TRADER_LEVERAGE_RATIO`.

This is the smallest design that matches the requested scope:

- the config lives at the same level as other process-wide runtime values
- the parsing and validation path is centralized
- leveraged execution code can read one normalized value from `Config`
- the spot path can ignore it entirely

The value is interpreted as a multiplier over available capital. `1.0` means no leverage. Values below `1.0` are invalid because they do not represent leverage in this project's vocabulary.

Important clarification: `leverage_ratio` is a maximum exposure cap, not a sizing instruction. Setting `TRADER_LEVERAGE_RATIO=2.0` must not automatically double every leveraged order. Existing task sizing still determines the requested order size first; the leverage ratio only rejects or caps leveraged requests whose nominal exposure would exceed the allowed global ceiling.

## Configuration Semantics
The configuration should behave as follows:

- environment variable name: `TRADER_LEVERAGE_RATIO`
- default: `1.0`
- type: float
- minimum allowed value: `1.0`
- invalid inputs: non-numeric, non-finite (`NaN`, `inf`), zero, negative, or values below `1.0`
- failure mode: raise a startup error during config parsing

The meaning is user-facing capital intent, not an exact execution budget after fees. That means the system may internally account for fee, precision, and slippage effects when translating the limit into order quantities.

`TRADER_LEVERAGE_RATIO` should also be included in `Config.export_env()` so subprocesses and operational scripts see the same validated value as the parent process.

## Scope of Application
The leverage ratio applies only when the execution path is explicitly leveraged:

- margin trading
- futures trading

It does not apply to spot trading. Spot should continue using its existing sizing logic and funding limits.

For leveraged paths, the enforcement should be layered:

1. Compute the existing task/requested notional using the current sizing rules.
2. Compute a leverage ceiling from available capital: `available_capital * cfg.leverage_ratio`.
3. Apply existing safety caps such as positive `live_trade_max_notional` on `auto_trade`; these caps are not multiplied by leverage.
4. Submit only the effective notional that is within all applicable caps and exchange constraints.

This keeps `TRADER_LEVERAGE_RATIO` independent from task sizing while still preventing an operator from exceeding the global leverage intent.

## Available Capital Definition
For this change, "available capital" should mean the best available quote-equivalent capital already owned by the account or configured runtime, before any new borrow created by the order:

- Prefer live exchange/account collateral or free quote balance when the leveraged path can read it reliably.
- Fall back to task `free` or global `cfg.cash` only for paths that already use those values as the runtime capital source.
- Do not treat exchange-reported `max_borrowable` as available capital. Borrow capacity remains a separate exchange constraint checked after the project-level leverage cap.

For short margin orders, the cap should be evaluated against the order's quote notional, even if the exchange borrow check is expressed in base-asset quantity.

## Data Flow
1. Process starts and loads `.env`.
2. `new_and_env()` reads `TRADER_LEVERAGE_RATIO`.
3. The value is validated and stored on `Config`.
4. Leveraged execution code reads `cfg.leverage_ratio` when determining the maximum allowed nominal exposure.
5. Margin borrow prechecks and futures/exchange-specific constraints run after the project-level leverage cap.
6. Spot execution ignores the field.

This keeps the leverage control at the framework level instead of scattering parsing logic across task handlers or strategy code.

## Error Handling
- Missing environment variable uses the default `1.0`.
- `0.8`, `0`, negative values, and malformed strings fail config loading.
- The error should identify `TRADER_LEVERAGE_RATIO` directly so operators can fix the environment quickly.
- The failure should happen before live execution starts.

## Implementation Notes
The existing `Config` class already centralizes process-wide configuration and `new_and_env()` already performs environment-to-config merging. The change should extend that path rather than introducing a parallel parser.

The rest of the system should consume the normalized numeric value from `Config` only. No business logic should re-parse the environment variable.

The first enforcement point should be the shared live/leveraged execution sizing boundary, not individual strategy code. In the current live auto path, that means applying the cap near requested-notional calculation before margin borrow precheck and before gateway submission. Future futures support should reuse the same normalized value and must not set exchange-side leverage above `cfg.leverage_ratio`.

## Testing
Automated coverage should include:

- default config loads `leverage_ratio=1.0`
- valid environment values are parsed correctly
- invalid environment values raise `ValueError`
- non-finite environment values such as `nan` and `inf` raise `ValueError`
- leveraged execution uses the configured ratio when enforcing exposure limits
- the ratio acts as a cap rather than an automatic size multiplier
- capped `auto_trade` still honors `live_trade_max_notional` as an independent hard cap
- margin short enforcement caps quote notional before base-asset borrow-capacity checks
- spot execution does not consult or depend on the new ratio
- the new config field is preserved by `to_dict()` / `safe_to_dict()` and `export_env()`

The tests should stay focused on the config layer and the leveraged execution entry point, not on exchange-specific integration details.

## Rollout Notes
This is a framework-layer addition, not a strategy-specific workaround.

The config name should be documented in the user-facing environment configuration section once implementation lands. The README will need a small update if the new variable is surfaced as part of normal operator setup.
