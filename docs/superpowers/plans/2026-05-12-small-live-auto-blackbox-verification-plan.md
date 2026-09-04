# Small Live Auto Blackbox Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production blackbox verification mechanism for `small_live_auto` that must pass spot-long + margin-short in a single run within 15 minutes, with mandatory execution-state DB closure and Binance Web manual verification evidence.

**Architecture:** Reuse the existing `binance_live_smoke` path as the single executable acceptance harness and strengthen it with preflight hard gates, explicit short-mode enforcement (`margin_cross`), breakeven (`RISK_UPDATE`) verification, DB execution-state closure checks, and operator-facing verification artifacts. Keep execution path unchanged (signal/test metadata only), and evaluate pass/fail only from externally observable outputs.

**Tech Stack:** Python, pytest, BinanceExchange (CCXT/native), TaskConfig/AutoExecutionRouter, execution_state persistence, shell script wrapper.

---

## Current Blocker / Execution Priority

The original acceptance run was blocked at `AC-005 / TEST-005` by Binance `MAX_NUM_ALGO_ORDERS`; Task 0 added same-context listing/cleanup support and the User accepted that cleanup evidence.

The current acceptance run is now blocked at `AC-006 / TEST-006` by a production execution defect in margin short breakeven replacement.

### Development Demand: Preserve Protection Order Identity For Breakeven Replacement

**Source acceptance item:** `AC-006 / TEST-006`

**Finding type:** `product_defect`

**Observed evidence:**
- Run command: `bash scripts/run_binance_live_smoke_e2e.sh`
- Run time: 2026-05-13 03:12:00 to 03:12:23 Asia/Shanghai
- Raw log: `/tmp/chainer_acceptance_live_smoke/test001_009_20260513_031200.log`
- Cross Margin short entry succeeded:
  - orderId `61720243463`, `BTCUSDT`, `SELL`, `MARKET`, `FILLED`, `0.00013 BTC`, `10.5054703 USDT`
  - trade id `6290659161`
- Native protection orders were created then canceled:
  - orderId `61720243547`, `BUY`, `STOP_LOSS`, `CANCELED`, stopPrice `84851.89`
  - orderId `61720243834`, `BUY`, `TAKE_PROFIT`, `CANCELED`, stopPrice `76770.75`
- Breakeven replacement failed:
  - operation ID `signal_event_id:margin-short-a671013e47-be`
  - operation type `RISK_UPDATE`
  - Binance error `{"code":-1102,"msg":"Mandatory parameter 'orderId' was not sent, was empty/null, or malformed."}`

**Expected production behavior:**
- After a live entry creates native protection orders, the framework must retain enough exchange identity (`orderId` and/or `clientOrderId`, scope, symbol, side, type) to update or replace the correct protection order during breakeven.
- If the old protection order identity is unavailable, the framework must fail safely before canceling/replacing protection, emit an operator-visible error, and avoid leaving an unclosed/unprotected position.

**Production risk:**
- A real production trade can enter a margin short and create initial protection, but fail during breakeven update because the replacement path does not send the required exchange `orderId`.
- The system may halt before close, leaving the account with position exposure that cannot be safely attributed or closed by the acceptance harness when larger pre-existing positions exist.

**Required behavior:**
- Persist and propagate native protection order IDs from entry/protection creation into the `RISK_UPDATE` path.
- For margin and spot flows, verify the replacement request contains the old protection `orderId` or a resolvable `clientOrderId` before sending a cancel/replace API call.
- Report old protection ID, cancel result, new protection ID, and new stop price in the live smoke report.
- If replacement cannot proceed, mark the operation failed with a clear reason and leave enough evidence for safe operator recovery.

**Safety constraints:**
- Do not blindly force-close an entire account-level position unless the system can attribute the position quantity to the current operation.
- Do not cancel unrelated protection orders without symbol/scope/order ownership evidence.

**Acceptance criteria:**
- `AC-006 / TEST-006` passes with Binance Web-visible old protection cancellation/replacement and new breakeven protection evidence.
- `AC-007 / TEST-007` subsequently closes only the test-created position quantity or otherwise proves safe residual state.
- `AC-008 / TEST-008` contains execution-state records for entry, breakeven replacement, and close.
- Regression tests cover missing protection `orderId` as a hard failure before Binance API submission.

**Implementation update:** 2026-05-13
- Added gateway fail-fast behavior: Binance live breakeven replacement no longer calls `replace_stop_order` when `replacement_of_order_id` is missing.
- Added router state propagation: successful native protection placement records the protection order ID by trade, and later `RISK_UPDATE` operations inherit that ID when missing.
- Added live smoke evidence propagation: the smoke harness extracts the old `STOP_LOSS` order ID from entry protection evidence and attaches it to breakeven replacement operations/reports.
- Added regression coverage:
  - `uv run pytest tests/test_execution_gateway_rollout_safety.py -k 'breakeven_replace_without_existing_protection_order_id or portable_backtrader' -q`
  - `uv run pytest tests/test_binance_live_smoke_e2e.py -k 'cleanup_blocking or list_open_orders or final_acceptance_gate or breakeven_update_carries or verify_entry_with_protection or verify_replace_protection or requires_trader_db or single_run_dual_flow' -q`

**Status:** implemented, pending renewed live acceptance rerun.

### Development Demand: Close Only Test-Owned Quantity And Use Correct Margin Close Side

**Source acceptance items:** `AC-004 / TEST-004`, `AC-007 / TEST-007`

**Finding type:** `product_defect`

**Observed evidence:**
- Run command: `bash scripts/run_binance_live_smoke_e2e.sh`
- Run time: 2026-05-13 04:10:15 to 04:10:54 Asia/Shanghai
- Raw log: `/tmp/chainer_acceptance_live_smoke/rerun_after_safe_stop_fix_20260513_041015.log`
- Binance Web/API evidence, 2026-05-13 04:09 to 04:12 Asia/Shanghai:
  - Spot entry order `61721809862`: `BUY MARKET FILLED`, `0.00013 BTC`, quote `10.50341890 USDT`
  - Spot close order `61721815150`: `SELL MARKET FILLED`, `0.00064 BTC`, quote `51.69612800 USDT`
  - Cross Margin short entry order `61721801732`: `SELL MARKET FILLED`, `0.00013 BTC`
  - Cross Margin final close-intended order `61721806307`: `SELL MARKET FILLED`, `0.00013 BTC`

**Expected production behavior:**
- Spot close must close only the quantity opened by the current router/trade, not the account's total free BTC balance.
- Cross Margin short close must buy back / repay the short exposure, not submit another sell order that increases short exposure.

**Production risk:**
- A live spot strategy can unintentionally sell user-owned BTC unrelated to the current strategy/test position.
- A live margin short close can increase short exposure instead of reducing it when routed through the CCXT driver.

**Required behavior:**
- Track live long quantity created by the router and use it for `SELL` close before falling back to account-level balance.
- For CCXT Cross Margin, map `OperateType.CLOSE` to `buy` with margin repay semantics.
- Preserve existing behavior for spot `SELL` and short `SHORT` entry.

**Safety constraints:**
- Do not force-close account-level positions unless the quantity is attributable to the current router/trade.
- Do not treat a green pytest wrapper as accepted unless Binance order history confirms close side and quantity.

**Implementation update:** 2026-05-13
- Added router-owned `real_long_position` tracking and used it for spot close.
- Changed CCXT Cross Margin `OperateType.CLOSE` side mapping to `buy` and `sideEffectType=AUTO_REPAY`.
- Added regression coverage:
  - `uv run pytest tests/test_live_auto_execution.py -k 'spot_close_uses_router_position or cross_margin_short_close_requires_known_short_exposure or small_live_auto_caps_real_long_order' -q`
  - `uv run pytest tests/test_ccxt_exchange_driver.py -k 'cross_margin_close_maps_to_buy_auto_repay or places_market_orders or cross_margin_cancel_all' -q`

**Status:** implemented, pending renewed live acceptance rerun.

Execution rule for the next cycle:
- Execute the breakeven replacement defect fix before rerunning the live acceptance suite.
- Do not continue downstream live tests while `AC-006 / TEST-006` is failing, because close and DB closure depend on successful replacement evidence.
- After the fix is implemented and locally verified, rerun from the approved live acceptance checklist with fresh open-order preflight evidence.

### Task 0: Add Same-Context Cleanup Support to Acceptance Harness

**Why this task exists:** The 2026-05-13 black-box run failed at `AC-005 / TEST-005` with Binance `MAX_NUM_ALGO_ORDERS` during `margin_short_entry`. This is an actionable precondition failure. Because this cleanup is needed to make the acceptance run possible, implement it as acceptance-test harness support first. Promote it to a reusable debug tool only if the User explicitly chooses that later.

**Files:**
- Modify: `src/trader/tools/binance_live_smoke.py`
- Modify: `scripts/run_binance_live_smoke_e2e.sh` only if wrapper output needs to expose cleanup evidence
- Test: `tests/test_binance_live_smoke_e2e.py` or a focused cleanup test file
- Docs: `docs/superpowers/acceptance/2026-05-13-small-live-auto-live-smoke/testing-checklist.md`

- [x] **Step 1: Define same-context cleanup contract**

The acceptance harness must:
- load the same `.env` style context as `scripts/run_binance_live_smoke_e2e.sh`
- target both Spot and Cross Margin for the configured symbol
- list open/protection/algo orders before cancellation
- cancel approved open/protection/algo orders
- list open/protection/algo orders after cancellation
- if canceling is insufficient and a position remains open, perform an approved force-close/settlement step with evidence
- emit machine-readable and human-readable evidence with timestamps, symbol, account scope, canceled order IDs, force-close order IDs, failures, and final residual count
- keep safety limits and live opt-in checks unchanged

- [x] **Step 2: Add tests for same-context config and evidence fields**

Run: `uv run pytest tests/test_binance_live_smoke_e2e.py -k cleanup -q`
Expected: PASS after implementation.

- [x] **Step 3: Implement cleanup inside the approved acceptance harness**

Preferred behavior: the live smoke harness detects `MAX_NUM_ALGO_ORDERS`, records before-state evidence, performs same-context cleanup once, records after-state evidence, then retries the blocked objective once.

- [x] **Step 4: Update acceptance testing checklist**

Update the approved acceptance document to name the same-context cleanup step as the allowed remediation for `MAX_NUM_ALGO_ORDERS`.

- [x] **Step 5: Stop for User verification**

After local verification of Task 0, stop. Do not rerun the full live acceptance suite until the User has reviewed the updated execution document and explicitly approves continuing.

### Task 1: Harden Runtime Preflight Gates

**Files:**
- Modify: `src/trader/tools/binance_live_smoke.py`
- Test: `tests/test_binance_live_smoke_e2e.py`

- [ ] **Step 1: Write failing preflight tests for spot/margin hard gates**

```python

def test_live_smoke_preflight_requires_trade_symbol_filters_and_notional_bounds(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "s")
    monkeypatch.setenv("CHAINERTRADER_SMALL_LIVE_MAX_NOTIONAL", "11")
    monkeypatch.setenv("CHAINERTRADER_LIVE_SMOKE_ENABLE_SPOT", "1")
    monkeypatch.setenv("CHAINERTRADER_LIVE_SMOKE_ENABLE_MARGIN", "1")
    # Fake exchange returns invalid exchange_info/filters -> RuntimeError expected.
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_binance_live_smoke_e2e.py -k preflight -q`
Expected: FAIL with missing preflight guard assertions.

- [ ] **Step 3: Implement preflight hard checks (before any order action)**

```python
# in run_binance_live_smoke_from_env
_preflight_exchange(exchange, symbol, max_notional, require_margin=False, report=report)
_preflight_exchange(margin_exchange, symbol, max_notional, require_margin=True, report=report)

# preflight validates:
# 1) exchange_info available
# 2) latest price available
# 3) quantity_for_notional valid
# 4) require_margin => is_cross_margin_ready() is True
# 5) emit report step with actionable manual instructions
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_binance_live_smoke_e2e.py -k preflight -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/trader/tools/binance_live_smoke.py tests/test_binance_live_smoke_e2e.py
git commit -m "feat: add hard preflight gates for live smoke verification"
```

### Task 2: Enforce Single-Run Dual-Flow Contract (Spot+Margin)

**Files:**
- Modify: `scripts/run_binance_live_smoke_e2e.sh`
- Modify: `src/trader/tools/binance_live_smoke.py`
- Test: `tests/test_binance_live_smoke_e2e.py`

- [ ] **Step 1: Write failing test for single-run dual-flow required mode**

```python

def test_live_smoke_requires_spot_and_margin_enabled_in_verification_mode(monkeypatch):
    monkeypatch.setenv("CHAINERTRADER_LIVE_SMOKE_ENABLE_SPOT", "0")
    monkeypatch.setenv("CHAINERTRADER_LIVE_SMOKE_ENABLE_MARGIN", "1")
    with pytest.raises(RuntimeError, match="single-run dual-flow"):
        run_binance_live_smoke_from_env()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_binance_live_smoke_e2e.py -k dual_flow -q`
Expected: FAIL.

- [ ] **Step 3: Implement strict dual-flow requirement and wrapper defaults**

```python
# in run_binance_live_smoke_from_env
if run_spot is not True or run_margin is not True:
    raise RuntimeError("single-run dual-flow verification requires spot=1 and margin=1")
```

```bash
# in scripts/run_binance_live_smoke_e2e.sh
export CHAINERTRADER_LIVE_SMOKE_ENABLE_MARGIN="${CHAINERTRADER_LIVE_SMOKE_ENABLE_MARGIN:-1}"
export CHAINERTRADER_LIVE_SMOKE_ENABLE_SPOT="${CHAINERTRADER_LIVE_SMOKE_ENABLE_SPOT:-1}"
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_binance_live_smoke_e2e.py -k dual_flow -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_binance_live_smoke_e2e.sh src/trader/tools/binance_live_smoke.py tests/test_binance_live_smoke_e2e.py
git commit -m "feat: require single-run spot+margin verification mode"
```

### Task 3: Force Short Path to Margin Cross

**Files:**
- Modify: `src/trader/tools/binance_live_smoke.py`
- Test: `tests/test_binance_live_smoke_e2e.py`

- [ ] **Step 1: Write failing test that asserts margin short task uses margin_cross**

```python

def test_margin_short_flow_sets_live_short_execution_margin_cross():
    cfg = _task_config(Symbol("BTC-USDT"), Decimal("11"), chainer_mode="BOTH", live_short_execution="margin_cross")
    assert cfg.live_short_execution == "margin_cross"
    assert cfg.requires_short_capability is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_binance_live_smoke_e2e.py -k margin_cross -q`
Expected: FAIL.

- [ ] **Step 3: Implement explicit short enforcement in smoke flow**

```python
# in _run_margin_short_flow
tcfg = _task_config(symbol, notional, chainer_mode="BOTH", live_short_execution="margin_cross")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_binance_live_smoke_e2e.py -k margin_cross -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/trader/tools/binance_live_smoke.py tests/test_binance_live_smoke_e2e.py
git commit -m "feat: force margin_cross for short verification flow"
```

### Task 4: Add Breakeven Replacement (`RISK_UPDATE`) in Both Flows

**Files:**
- Modify: `src/trader/tools/binance_live_smoke.py`
- Test: `tests/test_binance_live_smoke_e2e.py`

- [ ] **Step 1: Write failing tests that require breakeven replace steps in report**

```python

def test_live_smoke_report_contains_breakeven_replace_steps_when_enabled(...):
    report = run_binance_live_smoke_from_env()
    names = {s.name for s in report.steps}
    assert "spot_long_breakeven_replace" in names
    assert "margin_short_breakeven_replace" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_binance_live_smoke_e2e.py -k breakeven_replace -q`
Expected: FAIL.

- [ ] **Step 3: Implement `RISK_UPDATE` sequence for long and short**

```python
risk_update = _operation(OperateType.RISK_UPDATE, price)
_attach_breakeven_update(...)
update_outcome = router.route(risk_update)
_require_submitted(update_outcome, "... breakeven replace")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_binance_live_smoke_e2e.py -k breakeven_replace -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/trader/tools/binance_live_smoke.py tests/test_binance_live_smoke_e2e.py
git commit -m "feat: verify breakeven stop replacement in live smoke flows"
```

### Task 5: Make DB Execution-State Closure Mandatory

**Files:**
- Modify: `src/trader/tools/binance_live_smoke.py`
- Modify: `scripts/run_binance_live_smoke_e2e.sh`
- Test: `tests/test_binance_live_smoke_e2e.py`
- Optional Test Reference: `tests/test_execution_state_store.py`

- [ ] **Step 1: Write failing test for missing DB/runtime context gate**

```python

def test_live_smoke_requires_db_runtime_context_for_acceptance(monkeypatch):
    monkeypatch.delenv("TRADER_DB", raising=False)
    with pytest.raises(RuntimeError, match="TRADER_DB"):
        run_binance_live_smoke_from_env()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_binance_live_smoke_e2e.py -k trader_db -q`
Expected: FAIL.

- [ ] **Step 3: Implement mandatory DB gate and execution-state evidence fields**

```python
trader_db = os.getenv("TRADER_DB", "").strip()
if not trader_db:
    raise RuntimeError("TRADER_DB is required for execution_state closure verification")

# add report fields from outcome.execution_state_records
# include staged_execution_mode, status, order_id/protection_id evidence
```

```bash
# in wrapper script
if [ -z "${TRADER_DB:-}" ]; then
  echo "TRADER_DB must be set for DB closure verification."
  exit 1
fi
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_binance_live_smoke_e2e.py -k trader_db -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/trader/tools/binance_live_smoke.py scripts/run_binance_live_smoke_e2e.sh tests/test_binance_live_smoke_e2e.py
git commit -m "feat: require DB execution-state closure for live acceptance"
```

### Task 6: Emit Binance Web Manual Verification Checklist Artifact

**Files:**
- Modify: `src/trader/tools/binance_live_smoke.py`
- Modify: `README.md`
- Test: `tests/test_binance_live_smoke_e2e.py`

- [ ] **Step 1: Write failing test requiring manual verification instructions in report**

```python

def test_live_smoke_report_contains_binance_web_manual_checklist(...):
    report = run_binance_live_smoke_from_env()
    payload = report.to_dict()
    assert payload.get("manual_verification")
    assert any("Binance" in item for item in payload["manual_verification"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_binance_live_smoke_e2e.py -k manual_checklist -q`
Expected: FAIL.

- [ ] **Step 3: Implement operator checklist and criteria in output**

```python
# top-level report includes manual_verification[]:
# - Spot order history checks
# - Margin order history checks
# - Open-order protection checks
# - Fee/asset-change checks
# - Trace/order-id mapping checks
```

- [ ] **Step 4: Update README operation steps and expected checks**

```markdown
- Run command (single-run dual flow)
- Verify report fields
- Verify Binance Web pages and exact fields
- Acceptance pass/fail rule
```

- [ ] **Step 5: Run tests to verify pass**

Run: `uv run pytest tests/test_binance_live_smoke_e2e.py -k manual_checklist -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/trader/tools/binance_live_smoke.py README.md tests/test_binance_live_smoke_e2e.py
git commit -m "docs: add Binance Web manual acceptance checklist"
```

### Task 7: Add Blackbox Acceptance Runner and Final Gate

**Files:**
- Modify: `scripts/run_binance_live_smoke_e2e.sh`
- Modify: `tests/test_binance_live_smoke_e2e.py`

- [ ] **Step 1: Add timing gate test (<=15 minutes contract as metadata/assertion)**

```python

def test_live_smoke_reports_timing_budget_metadata(...):
    report = run_binance_live_smoke_from_env()
    data = report.to_dict()
    assert data["acceptance_contract"]["max_minutes"] == 15
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_binance_live_smoke_e2e.py -k timing_budget -q`
Expected: FAIL.

- [ ] **Step 3: Implement acceptance contract metadata and wrapper pass/fail summary**

```python
# report contains acceptance_contract:
# {"mode": "single_run_dual_flow", "max_minutes": 15, "required_steps": [...], "db_required": true}
```

```bash
# wrapper prints:
# 1) contract summary
# 2) report path
# 3) pass/fail with failed criteria
```

- [ ] **Step 4: Run all targeted tests**

Run: `uv run pytest tests/test_binance_live_smoke_e2e.py tests/test_execution_state_store.py -q`
Expected: PASS (except explicit live-skip test when creds absent).

- [ ] **Step 5: Commit**

```bash
git add scripts/run_binance_live_smoke_e2e.sh src/trader/tools/binance_live_smoke.py tests/test_binance_live_smoke_e2e.py
git commit -m "feat: finalize blackbox live acceptance contract and gates"
```

### Task 8: Blackbox Acceptance Execution (Operator Runbook)

**Files:**
- Modify: `README.md`
- Create: `configs/tasks/live/binance_blackbox_acceptance_checklist.json` (optional artifact schema if needed)

- [ ] **Step 1: Write operator runbook section**

```markdown
1) Preflight env checklist
2) Run single command
3) Review JSON report
4) Verify Binance Web evidence
5) Confirm DB execution_state closure
6) Decide PASS/FAIL
```

- [ ] **Step 2: Add explicit failure triage matrix**

```markdown
- preflight_spot failed -> check API / filters / balances
- margin_not_ready -> enable cross margin / permissions
- native_protection false -> reject acceptance
- missing execution_state -> reject acceptance
```

- [ ] **Step 3: Validate docs links and commands**

Run: `rg -n "run_binance_live_smoke_e2e|manual verification|execution_state" README.md`
Expected: all updated sections present and consistent.

- [ ] **Step 4: Commit**

```bash
git add README.md configs/tasks/live/binance_blackbox_acceptance_checklist.json
git commit -m "docs: publish blackbox production acceptance runbook"
```

---

## Spec Coverage Self-Review

- Single-run dual-flow within 15 minutes: covered by Task 2 and Task 7.
- Force `live_short_execution=margin_cross`: covered by Task 3.
- DB execution_state mandatory closure: covered by Task 5.
- Binance Web manual verification workflow: covered by Task 6 and Task 8.
- Stop-loss + breakeven replacement coverage: covered by Task 4.

No placeholders intentionally left; each task has concrete files, commands, expected outcomes, and commit actions.
