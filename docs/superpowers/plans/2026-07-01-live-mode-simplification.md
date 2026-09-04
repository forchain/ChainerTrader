# Live Mode Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `live_data_mode`, collapse live execution to `manual_notify` and `auto_trade`, delete the legacy live polling runtime path, and migrate repository-owned configs/docs to the simplified schema.

**Architecture:** The change is centered in the shared live-task framework, not in individual strategies. `TaskConfig` becomes the only schema gate, `TraderTask` always boots the persistent Backtrader live runner for `TRADER` tasks, and recovery/persisted-config handling is tightened so legacy modes fail loudly unless rewritten by an explicit migration path.

**Tech Stack:** Python, pytest, JSON task configs, Jinja/HTML task UI, OpenSpec markdown, README/docs

---

## File Structure

- `src/trader/task/task_config.py`
  Responsibility: parse, validate, normalize, and serialize live-task config fields.
- `src/trader/task/base_task.py`
  Responsibility: persisted `config_json` shape used by shutdown/recovery snapshots.
- `src/trader/task/task_manager.py`
  Responsibility: startup balance preflight, recovery-time runtime budget reconstruction, and the likely home for persisted live-config migration helpers.
- `src/trader/task/trader_task.py`
  Responsibility: live `TRADER` runtime startup path; delete the legacy full-window rerun loop.
- `src/trader/live/auto_execution.py`
  Responsibility: supported live execution mode constants and routing-mode normalization.
- `src/trader/execution/resolver.py`
  Responsibility: gateway resolution contract for `manual_notify` vs `auto_trade`.
- `src/trader/app/app.py`
  Responsibility: recovery/startup plumbing that reparses persisted `config_json` and must fail loudly on unmigrated legacy live configs.
- `src/trader/rpc/templates/tasks.html`
  Responsibility: task creation/edit form fields for live task options.
- `configs/tasks/live/*.json`
  Responsibility: repository-owned live sample configs; must all parse under the new schema.
- `tests/test_config.py`
  Responsibility: persisted config JSON round-trip and parser contract coverage.
- `tests/test_manual_live_trade_notifications.py`
  Responsibility: manual live mode config acceptance/rejection and no-order behavior.
- `tests/test_execution_gateway_contract.py`
  Responsibility: gateway resolution semantics for supported and removed modes.
- `tests/test_trader_task_backtrader_live_runtime.py`
  Responsibility: persistent live runner startup behavior and removed legacy live-mode assumptions.
- `tests/test_cli_task_handling.py`
  Responsibility: recovery persistence shape and shutdown behavior.
- `tests/test_realtime_live_demo_task.py`
  Responsibility: repository sample config contract.
- `README.md`
  Responsibility: user-facing live task configuration/runtime documentation.
- `openspec/specs/staged-live-auto-execution/spec.md`
  Responsibility: authoritative staged-live execution contract; must be updated to new two-mode model.
- `openspec/specs/manual-live-trade-notifications/spec.md`
  Responsibility: authoritative manual notify contract under the simplified model.
- `openspec/specs/execution-gateway-abstraction/spec.md`
  Responsibility: authoritative gateway-selection contract; must stop advertising removed live execution modes as supported.
- `openspec/specs/live-auto-order-safety/spec.md`
  Responsibility: authoritative auto-trade sizing and safety behavior.
- `openspec/specs/live-cross-margin-short-execution/spec.md`
  Responsibility: authoritative live short execution behavior after mode collapse.
- `openspec/changes/simplify-execution-modes-native-protection/**`
  Responsibility: active change artifacts that still describe removed modes.
- `docs/superpowers/specs/2026-06-10-live-task-restart-recovery-design.md`
  Responsibility: restart/recovery design that still references removed fields/modes.
- `docs/superpowers/specs/2026-06-17-task-fund-reservation-design.md`
  Responsibility: live reservation semantics docs that may still distinguish small/full modes.
- `docs/superpowers/specs/2026-06-30-leverage-ratio-design.md`
  Responsibility: active design doc that still mentions removed live execution semantics and must be updated or marked obsolete.
- `docs/superpowers/specs/2026-07-01-live-task-balance-preflight-design.md`
  Responsibility: live startup preflight docs that must reflect one `auto_trade` sizing contract.
- `docs/superpowers/specs/integrated-acceptance-testing-plan.md`
  Responsibility: acceptance guidance that must stop presenting removed modes as current usage.
- `docs/acceptance/**/acceptance-contract.md`
  Responsibility: active acceptance contracts; update or mark obsolete where they still require removed modes.

### Task 1: Add Persisted Live Config Migration Before Schema Tightening

**Files:**
- Create: `src/trader/task/persisted_live_config_migration.py`
- Create: `scripts/migrate_persisted_live_task_configs.py`
- Modify: `src/trader/task/task_manager.py`
- Modify: `src/trader/app/app.py`
- Test: `tests/test_cli_task_handling.py`
- Test: `tests/test_rpc_app_lifecycle.py`

- [ ] **Step 1: Write failing migration and recovery tests for persisted legacy live configs**

Add tests that assert:

```python
migrated = migrate_persisted_task_config_json('[{"task_type":"TRADER",...,"live_execution_mode":"small_live_auto","live_data_mode":"realtime"}]')
assert '"live_data_mode"' not in migrated
assert '"live_execution_mode": "auto_trade"' in migrated

manual = migrate_persisted_task_config_json('[{"task_type":"TRADER",...,"live_execution_mode":"manual_notify"}]')
assert '"live_execution_mode": "manual_notify"' in manual

with pytest.raises(ValueError, match="unsupported live_execution_mode: staged_auto_trade"):
    migrate_persisted_task_config_json('[{"task_type":"TRADER",...,"live_execution_mode":"staged_auto_trade"}]')
```

The recovery-path tests must also prove:
- migrated persisted config reparses and recovers

- [ ] **Step 2: Run the focused migration/recovery tests and confirm they fail**

Run: `uv run pytest tests/test_cli_task_handling.py tests/test_rpc_app_lifecycle.py -q`

Expected: failures because there is no explicit persisted-config migration path and recovery still tolerates or depends on legacy live config shape.

- [ ] **Step 3: Implement the operator-invokable one-shot persisted config migration command**

Add a focused helper plus a thin command surface with behavior equivalent to:

```python
def migrate_persisted_task_config_json(config_json: str) -> str:
    # remove live_data_mode
    # rewrite small_live_auto/full_live_auto -> auto_trade
    # keep manual_notify unchanged
    # reject staged_auto_trade/paper_auto/manual/notify/other unsupported values
```

Ownership:
- `src/trader/task/persisted_live_config_migration.py`: shared migration/validation logic
- `scripts/migrate_persisted_live_task_configs.py`: one-shot maintenance command operators can run before deploy

The command should scan persisted task rows, rewrite allowed legacy live configs in place, and fail non-zero with a concrete error if it encounters unsupported legacy values that cannot be migrated safely.

- [ ] **Step 4: Add an end-to-end test for invoking the migration command**

Add a command-path test that proves:
- persisted rows with `small_live_auto` / `full_live_auto` are rewritten to `auto_trade`
- persisted rows with `manual_notify` are preserved
- persisted rows with `staged_auto_trade`, `paper_auto`, `manual`, or `notify` cause the command to fail loudly

- [ ] **Step 5: Wire recovery to use only the migrated schema**

Update the recovery loader so:
- the maintenance command is the only migration entry point; recovery never rewrites persisted rows
- post-migration recovery reparses only the new schema
- unmigrated legacy persisted configs fail loudly with the same parser errors as direct config parsing

- [ ] **Step 6: Re-run the focused migration/recovery tests and confirm they pass**

Run: `uv run pytest tests/test_cli_task_handling.py tests/test_rpc_app_lifecycle.py -q`

Expected: PASS

- [ ] **Step 7: Commit the migration slice**

```bash
git add src/trader/task/persisted_live_config_migration.py scripts/migrate_persisted_live_task_configs.py src/trader/task/task_manager.py src/trader/app/app.py tests/test_cli_task_handling.py tests/test_rpc_app_lifecycle.py
git commit -m "feat: migrate persisted live task configs"
```

### Task 2: Tighten Config Schema And Persistence

**Files:**
- Modify: `src/trader/task/task_config.py`
- Modify: `src/trader/task/base_task.py`
- Modify: `src/trader/app/app.py`
- Test: `tests/test_config.py`
- Test: `tests/test_manual_live_trade_notifications.py`
- Test: `tests/test_cli_task_handling.py`

- [ ] **Step 1: Write failing parser and persistence tests for the new schema**

Add/replace tests that assert:

```python
with pytest.raises(ValueError, match="live_data_mode is no longer supported"):
    parse_task_config('[{"task_type":"TRADER",...,"live_data_mode":"realtime"}]')

with pytest.raises(ValueError, match="unsupported live_execution_mode: small_live_auto"):
    parse_task_config('[{"task_type":"TRADER",...,"live_execution_mode":"small_live_auto"}]')

with pytest.raises(ValueError, match="unsupported live_execution_mode: full_live_auto"):
    parse_task_config('[{"task_type":"TRADER",...,"live_execution_mode":"full_live_auto"}]')

with pytest.raises(ValueError, match="unsupported live_execution_mode: staged_auto_trade"):
    parse_task_config('[{"task_type":"TRADER",...,"live_execution_mode":"staged_auto_trade"}]')

with pytest.raises(ValueError, match="unsupported live_execution_mode: paper_auto"):
    parse_task_config('[{"task_type":"TRADER",...,"live_execution_mode":"paper_auto"}]')

with pytest.raises(ValueError, match="unsupported live_execution_mode: manual"):
    parse_task_config('[{"task_type":"TRADER",...,"live_execution_mode":"manual"}]')

with pytest.raises(ValueError, match="unsupported live_execution_mode: notify"):
    parse_task_config('[{"task_type":"TRADER",...,"live_execution_mode":"notify"}]')

task = parse_task_config('[{"task_type":"TRADER",...,"live_execution_mode":"manual_notify"}]')[0]
assert task.live_execution_mode == "manual_notify"
assert "live_data_mode" not in task.to_dict()

persisted = BaseTask(task, Config(tasks="[]"), Logger(Config(tasks="[]"))).ts.config_json
assert '"live_data_mode"' not in persisted
```

- [ ] **Step 2: Run the targeted parser tests and confirm they fail for the expected legacy behavior**

Run: `uv run pytest tests/test_config.py tests/test_manual_live_trade_notifications.py -q`

Expected: failures showing `live_data_mode` is still accepted/serialized and legacy live execution modes still normalize successfully.

- [ ] **Step 3: Remove `live_data_mode` from `TaskConfig` and restrict execution mode normalization**

Implement the minimal schema change:

```python
class TaskConfig:
    def __init__(..., live_execution_mode: str = "auto_trade", ...):
        self.live_execution_mode = normalize_live_execution_mode(live_execution_mode)
        # delete self.live_data_mode entirely

def parse_task_config(...):
    if "live_data_mode" in tcd:
        raise ValueError("live_data_mode is no longer supported; remove it from the task config")
```

Also update `to_dict()` and persisted config serialization so `live_data_mode` is never emitted.

- [ ] **Step 4a: Make recovery reparse fail with the same parser errors for unmigrated legacy rows**

Add/adjust recovery-path tests to assert:

```python
with pytest.raises(ValueError, match="live_data_mode is no longer supported"):
    asyncio.run(app._recover_running_tasks_in_background())
```

Also add a dedicated assertion that task recovery identity/config persistence no longer includes `live_data_mode`, using the production code path that computes/persists the recovery config shape.

- [ ] **Step 5: Simplify live execution mode support to only `manual_notify` and `auto_trade`**

Update the normalization layer so only these values survive:

```python
SUPPORTED_LIVE_EXECUTION_MODES = {"manual_notify", "auto_trade"}

if mode not in SUPPORTED_LIVE_EXECUTION_MODES:
    raise ValueError(f"unsupported live_execution_mode: {raw}")
```

Remove shorthand alias acceptance such as `manual` / `notify`, per the approved breaking-change policy. Keep the error text direct enough that stale external configs identify the rejected value immediately.

- [ ] **Step 6: Re-run the targeted parser tests and confirm they pass**

Run: `uv run pytest tests/test_config.py tests/test_manual_live_trade_notifications.py tests/test_cli_task_handling.py -q`

Expected: PASS

- [ ] **Step 7: Commit the schema-only slice**

```bash
git add src/trader/task/task_config.py src/trader/task/base_task.py src/trader/app/app.py tests/test_config.py tests/test_manual_live_trade_notifications.py tests/test_cli_task_handling.py
git commit -m "refactor: simplify live task config schema"
```

### Task 3: Remove Legacy Runtime Branch And Unify Auto-Trade Semantics

**Files:**
- Modify: `src/trader/task/trader_task.py`
- Modify: `src/trader/live/auto_execution.py`
- Modify: `src/trader/execution/resolver.py`
- Modify: `src/trader/task/task_manager.py`
- Modify: `src/trader/app/app.py`
- Test: `tests/test_trader_task_backtrader_live_runtime.py`
- Test: `tests/test_execution_gateway_contract.py`
- Test: `tests/test_live_auto_execution.py`
- Test: `tests/test_account_fund_reservation.py`
- Test: `tests/test_cli_task_handling.py`
- Test: `tests/test_rpc_app_lifecycle.py`

- [ ] **Step 1: Write failing runtime and gateway tests for the simplified behavior**

Add/adjust tests that assert:

```python
manual = TaskConfig(..., live_execution_mode="manual_notify")
await TraderTask(manual, ...).start(queue)
assert backtrader_live_runner_started_once is True
assert no_exchange_order_submission is True

task = TaskConfig(..., live_execution_mode="auto_trade")
await TraderTask(task, ...).start(queue)
assert backtrader_live_runner_started_once is True
assert legacy_window_rerun_path_not_called is True
assert auto_execution_router_received_eligible_operation is True
assert live_gateway_invoked_for_eligible_operation is True

resolved = resolve_execution_gateway(live_execution_mode="auto_trade", live_trade_max_notional=25.0)
assert resolved.gateway_mode == GatewayMode.BINANCE_LIVE
assert resolved.max_notional == 25.0
assert resolved.requires_live_order_cap is True

with pytest.raises(GatewayResolutionError, match="unsupported live_execution_mode: full_live_auto"):
    resolve_execution_gateway(live_execution_mode="full_live_auto")

with pytest.raises(GatewayResolutionError, match="unsupported live_execution_mode: staged_auto_trade"):
    resolve_execution_gateway(live_execution_mode="staged_auto_trade")

with pytest.raises(GatewayResolutionError, match="unsupported live_execution_mode: paper_auto"):
    resolve_execution_gateway(live_execution_mode="paper_auto")
```

Also adjust budget tests to prove:
- `strategy_cash = free if free > 0 else global cash`
- preflight/recovery/order cap use `min(strategy_cash, live_trade_max_notional)` when cap is positive
- `manual_notify` still never submits orders
- recovery after persisted-config migration succeeds, but recovery against an unmigrated legacy row still fails loudly
- task recovery identity/config persistence no longer includes `live_data_mode`

- [ ] **Step 2: Run the focused runtime/execution tests and confirm they fail**

Run: `uv run pytest tests/test_trader_task_backtrader_live_runtime.py tests/test_execution_gateway_contract.py tests/test_live_auto_execution.py tests/test_account_fund_reservation.py tests/test_cli_task_handling.py tests/test_rpc_app_lifecycle.py -q`

Expected: failures due to remaining `live_data_mode` branching, `small_live_auto` / `full_live_auto` semantics, and persisted config expectations.

- [ ] **Step 3: Delete the legacy polling live runtime path from `TraderTask.start()`**

Refactor startup to one live path:

```python
async def start(self, queue):
    ...
    await self.start_realtime(queue, strategy)
```

Delete the branch that repeatedly downloads a full K-line window and rebuilds `Node` for each candle. Remove helpers/imports that become unused because of that deletion.

- [ ] **Step 4: Collapse auto execution and gateway resolution to the two supported modes**

Implement the minimal runtime contract:

```python
REAL_AUTO_MODES = {"auto_trade"}
SUPPORTED_LIVE_EXECUTION_MODES = {"manual_notify", "auto_trade"}

if mode == "manual_notify":
    return notification_only
if mode == "auto_trade":
    return live_gateway
```

Preserve order-cap semantics by moving the old `small_live_auto` cap behavior behind `live_trade_max_notional > 0`, not behind a mode name.

- [ ] **Step 5: Update startup preflight and recovery budget logic to the explicit `auto_trade` sizing contract**

Use one calculation path:

```python
strategy_cash = cfg.free if cfg.free > 0 else self.cfg.cash
order_notional_cap = cfg.live_trade_max_notional if cfg.live_trade_max_notional > 0 else None
effective_live_budget = min(strategy_cash, order_notional_cap) if order_notional_cap else strategy_cash
```

Use `effective_live_budget` for:
- startup balance preflight
- recovered runtime budget reconstruction
- max notional enforcement for order routing

Use `strategy_cash` for the strategy simulation budget only.

- [ ] **Step 6: Re-run the focused runtime/execution tests and confirm they pass**

Run: `uv run pytest tests/test_trader_task_backtrader_live_runtime.py tests/test_execution_gateway_contract.py tests/test_live_auto_execution.py tests/test_account_fund_reservation.py tests/test_cli_task_handling.py tests/test_rpc_app_lifecycle.py -q`

Expected: PASS

- [ ] **Step 7: Commit the runtime slice**

```bash
git add src/trader/task/trader_task.py src/trader/live/auto_execution.py src/trader/execution/resolver.py src/trader/task/task_manager.py src/trader/app/app.py tests/test_trader_task_backtrader_live_runtime.py tests/test_execution_gateway_contract.py tests/test_live_auto_execution.py tests/test_account_fund_reservation.py tests/test_cli_task_handling.py tests/test_rpc_app_lifecycle.py
git commit -m "refactor: unify live runtime and execution modes"
```

### Task 4: Migrate Repository Configs And Live Task UI

**Files:**
- Modify: `src/trader/rpc/templates/tasks.html`
- Modify: `configs/tasks/live/manual_notify_btc_1m.json`
- Modify: `configs/tasks/live/binance_smoke_test.json`
- Modify: `configs/tasks/live/production_fast_signal_smoke.json`
- Modify: `configs/tasks/live/production_fast_signal_mixed_mode_smoke.json`
- Rename or replace: `configs/tasks/live/small_live_auto_btc_1m.json`
- Rename or replace: `configs/tasks/live/full_live_auto_btc_1m.json`
- Rename or replace: `configs/tasks/live/realtime_macd_triple_divergence_top10_production.json`
- Test: `tests/test_realtime_live_demo_task.py`
- Test: `tests/test_task_config_paths.py`
- Test: `tests/test_live_monitor_api_contract.py`

- [ ] **Step 1: Write failing tests for sample config parsing and UI field definitions**

Add/adjust tests that assert:

```python
trader_fields = TASK_FIELD_DEFS["TRADER"]
assert all(field["key"] != "live_data_mode" for field in trader_fields)
mode_field = next(field for field in trader_fields if field["key"] == "live_execution_mode")
assert mode_field["options"] == ["auto_trade", "manual_notify"]

for path in active_live_config_paths():
    tasks = parse_task_config(str(path))
    assert tasks
    assert all(task.live_execution_mode in {"manual_notify", "auto_trade"} for task in tasks)
    assert all("live_data_mode" not in task.to_dict() for task in tasks)
```

Update any contract test that still expects serialized live monitor payloads to contain `live_data_mode`.

- [ ] **Step 2: Run the targeted config/UI tests and confirm they fail**

Run: `uv run pytest tests/test_realtime_live_demo_task.py tests/test_task_config_paths.py tests/test_live_monitor_api_contract.py -q`

Expected: failures due to stale config filenames, stale live mode values, and UI field definitions still exposing removed options.

- [ ] **Step 3: Remove the live data selector and stale execution options from the task UI**

Update `TASK_FIELD_DEFS.TRADER` so the live fields reduce to:

```javascript
{ key: 'live_execution_mode', label: '执行模式', type: 'select', default: 'auto_trade', options: ['auto_trade', 'manual_notify'] }
```

Delete the `live_data_mode` field definition entirely.

- [ ] **Step 4: Migrate repository-owned live task JSON files to the new schema**

For each active live config:
- remove every `live_data_mode`
- change every `small_live_auto` and `full_live_auto` to `auto_trade`
- preserve `manual_notify` unchanged
- preserve any `live_trade_max_notional` value

Rename sample files whose names encode removed semantics so active samples no longer advertise old modes.

- [ ] **Step 4a: Add an explicit filename audit for removed mode naming**

Run:

```bash
rg --files configs/tasks/live | rg 'realtime_|small_live_auto|full_live_auto'
```

Expected after the rename/delete work: no active sample filename still encodes removed data-mode or removed execution-mode semantics.

- [ ] **Step 5: Re-run the targeted config/UI tests and confirm they pass**

Run: `uv run pytest tests/test_realtime_live_demo_task.py tests/test_task_config_paths.py tests/test_live_monitor_api_contract.py -q`

Expected: PASS

- [ ] **Step 6: Commit the config/UI slice**

```bash
git add src/trader/rpc/templates/tasks.html configs/tasks/live tests/test_realtime_live_demo_task.py tests/test_task_config_paths.py tests/test_live_monitor_api_contract.py
git commit -m "refactor: migrate live task configs and ui"
```

### Task 5: Update README, OpenSpec, Acceptance Docs, And Historical References

**Files:**
- Modify: `README.md`
- Modify: `openspec/specs/staged-live-auto-execution/spec.md`
- Modify: `openspec/specs/manual-live-trade-notifications/spec.md`
- Modify: `openspec/specs/execution-gateway-abstraction/spec.md`
- Modify: `openspec/specs/live-auto-order-safety/spec.md`
- Modify: `openspec/specs/live-cross-margin-short-execution/spec.md`
- Modify: `openspec/changes/simplify-execution-modes-native-protection/proposal.md`
- Modify: `openspec/changes/simplify-execution-modes-native-protection/design.md`
- Modify: `openspec/changes/simplify-execution-modes-native-protection/tasks.md`
- Modify: `openspec/changes/simplify-execution-modes-native-protection/specs/execution-gateway-abstraction/spec.md`
- Modify: `openspec/changes/simplify-execution-modes-native-protection/specs/staged-live-auto-execution/spec.md`
- Modify: `openspec/changes/simplify-execution-modes-native-protection/specs/manual-live-trade-notifications/spec.md`
- Modify: `docs/superpowers/specs/2026-06-10-live-task-restart-recovery-design.md`
- Modify: `docs/superpowers/specs/2026-06-17-task-fund-reservation-design.md`
- Modify: `docs/superpowers/specs/2026-06-30-leverage-ratio-design.md`
- Modify: `docs/superpowers/specs/2026-07-01-live-task-balance-preflight-design.md`
- Modify: `docs/superpowers/specs/integrated-acceptance-testing-plan.md`
- Modify as needed: `docs/acceptance/**/acceptance-contract.md`
- Modify as needed: `docs/acceptance/**/testing-checklist.md`
- Modify as needed: `docs/acceptance/**/execution-report.md`
- Modify as needed: `docs/superpowers/plans/**`

- [ ] **Step 1: Write a failing repository-surface audit check**

Create or adjust a lightweight doc/config audit test or scripted assertion that fails when active surfaces still present removed semantics, for example:

```bash
rg -n "live_data_mode|small_live_auto|full_live_auto|staged_auto_trade|paper_auto" README.md openspec/specs openspec/changes docs/acceptance docs/superpowers/specs docs/superpowers/plans configs/tasks/live tests
rg --files configs/tasks/live | rg 'realtime_|small_live_auto|full_live_auto'
```

Expected allowed matches after cleanup:
- parser/gateway rejection tests
- migration/rejection docs that clearly describe the values as removed
- explicitly historical/archive artifacts only

- [ ] **Step 2: Run the audit and capture the current failures**

Run:

```bash
rg -n "live_data_mode|small_live_auto|full_live_auto|staged_auto_trade|paper_auto" README.md openspec/specs openspec/changes docs/acceptance docs/superpowers/specs docs/superpowers/plans configs/tasks/live
rg --files configs/tasks/live | rg 'realtime_|small_live_auto|full_live_auto'
```

Expected: many matches in README/OpenSpec/spec docs that still describe removed modes as active.

- [ ] **Step 3: Update active docs to the new public contract**

Make the documentation consistent:
- one live runtime fed by the CCXT polling scheduler's newly closed candles
- supported execution modes are only `manual_notify` and `auto_trade`
- `live_data_mode` is removed
- `auto_trade` sizing is controlled by `free` and optional `live_trade_max_notional`
- rollback guidance uses `auto_trade` and `manual_notify`, not `small_live_auto` / `full_live_auto`

Mark any retained older documents as historical/non-authoritative if they must stay.

- [ ] **Step 4: Re-run the audit and confirm only intentional historical/rejection matches remain**

Run:

```bash
rg -n "live_data_mode|small_live_auto|full_live_auto|staged_auto_trade|paper_auto" README.md openspec/specs openspec/changes docs/acceptance docs/superpowers/specs docs/superpowers/plans configs/tasks/live
rg --files configs/tasks/live | rg 'realtime_|small_live_auto|full_live_auto'
```

Expected: no active user-facing guidance still presents those values as supported current config.

- [ ] **Step 5: Commit the docs slice**

```bash
git add README.md openspec/specs openspec/changes docs/superpowers/specs docs/superpowers/plans docs/acceptance
git commit -m "docs: align live mode documentation with simplified config"
```

### Task 6: Final Regression Verification

**Files:**
- Modify: none expected
- Test: repository-wide targeted regression selection for this change

- [ ] **Step 1: Run the full targeted regression suite for the simplified live mode surface**

Run:

```bash
uv run pytest \
  tests/test_config.py \
  tests/test_manual_live_trade_notifications.py \
  tests/test_execution_gateway_contract.py \
  tests/test_live_auto_execution.py \
  tests/test_trader_task_backtrader_live_runtime.py \
  tests/test_account_fund_reservation.py \
  tests/test_cli_task_handling.py \
  tests/test_rpc_app_lifecycle.py \
  tests/test_task_config_paths.py \
  tests/test_realtime_live_demo_task.py \
  tests/test_live_monitor_api_contract.py -q
```

Expected: PASS

- [ ] **Step 2: Run a repository-wide search for stale active code/config references**

Run:

```bash
rg -n "live_data_mode|small_live_auto|full_live_auto|staged_auto_trade|paper_auto|\"manual\"|\"notify\"" src tests configs README.md openspec docs
rg --files configs/tasks/live | rg 'realtime_|small_live_auto|full_live_auto'
```

Expected:
- active code may still contain rejection paths for removed values
- tests may contain rejection assertions and migration checks
- historical/archive docs may still mention removed values only if clearly labeled

Use exact alias-focused patterns instead of broad prose matches, for example:

```bash
rg -n '"live_execution_mode"\\s*:\\s*"manual"|normalize_live_execution_mode\\([^\\n]*"manual"|_normalize_live_execution_mode\\([^\\n]*"manual"' src tests configs README.md openspec docs
rg -n '"live_execution_mode"\\s*:\\s*"notify"|normalize_live_execution_mode\\([^\\n]*"notify"|_normalize_live_execution_mode\\([^\\n]*"notify"' src tests configs README.md openspec docs
```

- [ ] **Step 3: Inspect the diff for accidental collateral changes**

Run: `git diff --stat && git diff --check`

Expected: only files related to this simplification are changed; no whitespace errors.

- [ ] **Step 4: Commit any final fixups if needed**

```bash
git add -A
git commit -m "test: finalize live mode simplification verification"
```
