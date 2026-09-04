---
name: Update ChainerTrader Pine v3 Direction & Short-Support Logic
overview: ""
todos:
  - id: reintroduce-direction-inputs
    content: Add Allow short and Direction inputs in `chainer` group and compute effective `dir` based on allowShort + direction rules.
    status: completed
  - id: compute-direction-aware-signals
    content: Derive `tradeEntrySignal` and `tradeExitSignal` from raw MA Cross signals according to LONG/SHORT direction and allowShort flag.
    status: completed
    dependencies:
      - reintroduce-direction-inputs
  - id: wire-state-machine-to-signals
    content: Replace uses of `effectiveEntrySignal`/`effectiveExitSignal` in entry/exit logic with the new direction-aware trading signals; ensure library calls use `dir`.
    status: completed
    dependencies:
      - compute-direction-aware-signals
  - id: align-plots-and-markers
    content: Update all `plotshape` markers (E/X, confirm/fail, SL/BE/TP visuals) to track the new trading signals and direction.
    status: completed
    dependencies:
      - wire-state-machine-to-signals
  - id: verify-long-short-behavior
    content: Run visual and debug-log checks for LONG-only and SHORT-enabled modes to confirm behavior matches the specified v3 rules.
    status: completed
    dependencies:
      - align-plots-and-markers
---

# Update ChainerTrader Pine v3 Direction & Short-Support Logic

### Goal

Support a richer **direction model** in `[I]Chainer` Pine indicator so that:

- A user can choose whether **shorts are allowed** and a separate **operation direction**.
- Entry/exit signals are mapped correctly for LONG vs SHORT according to your rules.
- When shorts are disallowed, the strategy behaves as **LONG-only**, ignoring short opportunities.

### Plan

1. **Re-introduce & refine direction inputs**  

- In [`src/pine_scripts/indicators/chainer_trader.pine`](src/pine_scripts/indicators/chainer_trader.pine), under the *CHAIER* group:
    - Add `Allow short` back as `allowShort = input.bool(...)`.
    - Add a new `Direction` input, e.g. `direction = input.string("LONG", "Direction", options=["LONG", "SHORT"], group="chainer")`.
- Compute the actual working direction:
    - If `allowShort` is **false**, force `dir = "LONG"` regardless of `direction` input.
    - If `allowShort` is **true**, set `dir` from the `direction` input.
- Update comments and debug logging to reflect that `dir` can now be `LONG` or `SHORT`.

2. **Remap MA Cross signals based on direction**  

- Keep existing raw cross signals:
    - `longEntryRaw = entrySignal  // fast above slow`
    - `longExitRaw  = exitSignal   // fast below slow`
- Define direction-aware trading signals:
    - If `dir == "LONG"`:
    - `tradeEntrySignal = longEntryRaw`
    - `tradeExitSignal  = longExitRaw`
    - If `dir == "SHORT"` and `allowShort` is **true**:
    - `tradeEntrySignal = longExitRaw`   (死叉为进场)
    - `tradeExitSignal  = longEntryRaw`  (金叉为出场)
    - If `allowShort` is **false** and `direction == "SHORT"` (or any non-LONG):
    - `tradeEntrySignal = false`
    - `tradeExitSignal  = false` (完全不操作)
- Keep `entrySignal` / `exitSignal` as **visual-only** (optional) or switch all plots to use `tradeEntrySignal` / `tradeExitSignal` for a cleaner, direction-aware view.

3. **Wire trading state machine to direction-aware signals**  

- Replace all uses of `effectiveEntrySignal` and `effectiveExitSignal` in the trading logic with `tradeEntrySignal` and `tradeExitSignal`:
    - Entry trigger block (setting `pendingEntry`, `hasTrade`, `initialStop`, etc.).
    - Exit trigger block (setting `pendingExit`, `exitKeyBarIndex`, etc.).
    - Any other branches that currently assume `entrySignal` means LONG-only.
- Ensure:
    - Library calls (`stopPrice`, `entryConfirm`, `exitConfirm`, `breakevenPrice`, `riskRewardPrice`, `stopHit`) all use the current `dir` so that LONG/SHORT logic is handled inside your common library.

4. **Align all markers and labels with new signals**  

- Update plotting section so that:
    - Entry `E` markers use `tradeEntrySignal`.
    - Exit `X` markers use `tradeExitSignal`.
    - Entry confirm/failed flags (`entryConfirmSignal`, `entryFailSignal`) are triggered only when the corresponding `tradeEntrySignal` has created/invalidated a position in that direction.
    - Exit confirm/failed flags (`exitConfirmSignal`, `exitFailSignal`) follow `tradeExitSignal` events in the current direction.
- Verify that when `Direction = SHORT` and `Allow short = true`, charts show inverted entry/exit points consistent with your description; when `Allow short = false`, only LONG-side markers appear even if MA Cross produces short-side opportunities.

5. **Sanity-check with logs & visual tests**  

- Use the existing debug logging block in [`src/pine_scripts/indicators/chainer_trader.pine`](src/pine_scripts/indicators/chainer_trader.pine) to log `dir`, `allowShort`, `tradeEntrySignal`, `tradeExitSignal` for a few bars.
- Visually verify on the chart for both configurations:
    - `Allow short = false` → only LONG entries/exits; SHORT crossovers produce no trades.