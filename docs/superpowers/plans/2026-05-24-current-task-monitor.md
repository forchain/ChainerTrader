# Current Task Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace live-only monitor semantics with a unified current-task monitor that defaults to running task, falls back to latest finished task, and routes the center view by task type.

**Architecture:** Keep `/admin/live` as compatibility route and evolve the page into a task-centric shell. Add a current-task API under existing live API namespace to return selected task, task list, renderer kind, and task snapshot. Reuse existing live snapshot/event plumbing for `TRADER` tasks and provide read-only task snapshots for non-live task types in phase 1.

**Tech Stack:** FastAPI, Jinja templates, vanilla JavaScript, pytest.

---

### Task 1: Introduce Current-Task API Contract

**Files:**
- Modify: `src/trader/rpc/api/live.py`
- Test: `tests/test_live_monitor_api_contract.py`

- [x] **Step 1: Add failing contract tests for `/api/live/current-task`**
- [x] **Step 2: Implement task selection and renderer mapping**
- [x] **Step 3: Reuse live snapshot for `TRADER`; add generic snapshots for others**
- [x] **Step 4: Run targeted contract tests**

### Task 2: Rename UI Concept To Task Monitor

**Files:**
- Modify: `src/trader/rpc/templates/base.html`
- Modify: `src/trader/rpc/templates/live.html`
- Test: `tests/test_live_monitor_frontend_assets.py`

- [x] **Step 1: Update nav and page title text from live monitor to task monitor**
- [x] **Step 2: Keep layout shell and route compatibility intact**
- [x] **Step 3: Update template asset tests**

### Task 3: Route Frontend Workspace By Task Type

**Files:**
- Modify: `src/trader/rpc/static/js/live-monitor.js`
- Test: `tests/test_live_monitor_frontend_assets.py`

- [x] **Step 1: Switch bootstrap data source to `/api/live/current-task`**
- [x] **Step 2: Add task selection flow using `task_id` and `display_context`**
- [x] **Step 3: Keep live chart path for `live` renderer and add read-only renderers for `backtest/data/generic`**
- [x] **Step 4: Ensure SSE only runs for live renderer**
- [x] **Step 5: Run targeted frontend asset tests**

### Task 4: Verify Integrated Behavior

**Files:**
- Test: `tests/test_live_monitor_api_contract.py`
- Test: `tests/test_live_monitor_frontend_assets.py`
- Test: `tests/test_rpc.py`

- [x] **Step 1: Run focused pytest suite**
- [x] **Step 2: Confirm no regression in RPC route lifecycle coverage**
- [x] **Step 3: Prepare commit with spec + plan + implementation**
