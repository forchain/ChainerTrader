# Multi-User Admin and Task Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first-phase multi-user console with database-backed login, user-owned strategy/task data, encrypted per-user exchange credentials, and HTMX-first server-rendered UI improvements.

**Architecture:** Keep FastAPI + Jinja + Bootstrap as the first-phase web stack. Add a thin auth/account boundary around the existing RPC app, then incrementally add ownership to task and credential flows before restructuring task-oriented pages. Live trading remains a task type and live monitoring becomes a specialized view over live tasks.

**Tech Stack:** FastAPI, Jinja2, Bootstrap, HTMX, optional Alpine.js, Tortoise ORM, Argon2 password hashing, Fernet-style credential encryption via `cryptography`.

---

## Spec Reference
- `docs/superpowers/specs/2026-05-15-multi-user-admin-and-task-console-design.md`

## Important Existing State
- Current web app lives in `src/trader/rpc/app.py`.
- Current Basic Auth middleware lives in `src/trader/rpc/auth.py`.
- Current DB models live in `src/trader/database/models.py`.
- Current migrations live in `src/trader/database/migrations/`.
- Current task APIs live in `src/trader/rpc/api/tasks.py` and `src/trader/rpc/api/task.py`.
- Current task persistence lives in `src/trader/database/task.py`.
- Current frontend templates live in `src/trader/rpc/templates/`.
- Current static JS lives in `src/trader/rpc/static/js/`.
- There are pre-existing draft edits in `src/trader/exchange/exchange_config.py` and `src/trader/task/task_config.py` from an earlier `account_id` approach. Reconcile them with this plan before implementing task routing.

## File Structure

### New Files
- `src/trader/auth/passwords.py`: password validation, hashing, verification, temporary password generation.
- `src/trader/auth/sessions.py`: session token creation, hashing, expiry helpers.
- `src/trader/auth/credentials.py`: service-key validation and exchange credential encryption/decryption helpers.
- `src/trader/auth/context.py`: current-user request dependency and authorization helpers.
- `src/trader/database/user.py`: repository methods for users and sessions.
- `src/trader/database/exchange_credential.py`: repository methods for encrypted user exchange credentials.
- `src/trader/database/strategy_config.py`: repository methods for saved strategy configs.
- `src/trader/database/migrations/0003_users_auth_and_ownership.py`: database migration for first-phase auth and ownership schema.
- `src/trader/rpc/api/auth.py`: login, logout, register, current user, change password endpoints.
- `src/trader/rpc/api/admin_users.py`: administrator user management and password reset endpoints.
- `src/trader/rpc/api/account.py`: current-user account and exchange credential endpoints.
- `src/trader/rpc/templates/login.html`: login page.
- `src/trader/rpc/templates/register.html`: registration page.
- `src/trader/rpc/templates/change_password.html`: forced and voluntary password change page.
- `src/trader/rpc/templates/account.html`: current-user account/API key page.
- `src/trader/rpc/templates/admin_users.html`: admin user management page.
- `src/trader/rpc/templates/partials/*.html`: HTMX partials for user table, account credential form, task lists.
- `tests/test_auth_passwords.py`
- `tests/test_auth_sessions.py`
- `tests/test_rpc_session_auth.py`
- `tests/test_admin_user_management.py`
- `tests/test_exchange_credentials.py`
- `tests/test_task_ownership.py`

### Modified Files
- `pyproject.toml`: add `argon2-cffi` and `cryptography`.
- `src/trader/common/config.py`: add `TRADER_SECRET_KEY`, session settings, and auth bootstrap helpers.
- `src/trader/database/models.py`: add auth/account models and ownership fields.
- `src/trader/database/manager.py`: include new required tables and initialize new repositories.
- `src/trader/rpc/app.py`: replace Basic Auth flow with session auth middleware/dependencies and new pages.
- `src/trader/rpc/auth.py`: replace or deprecate Basic Auth middleware with session-auth middleware.
- `src/trader/rpc/templates/base.html`: add role-aware navigation and HTMX script include.
- `src/trader/rpc/templates/tasks.html`: move toward task center and HTMX partial refreshes.
- `src/trader/rpc/templates/live.html`: ensure live monitor is scoped to current user's live tasks.
- `src/trader/rpc/api/live.py`: filter live strategies and events by current user.
- `src/trader/task/task_config.py`: carry `user_id` or an internal owner reference when creating task runs.
- `src/trader/task/task_manager.py`: preserve owner metadata and route live exchange credentials by task owner.
- `src/trader/database/task.py`: persist and query task ownership.

---

## Task 0: Reconcile Current Draft Changes

**Files:**
- Inspect: `src/trader/exchange/exchange_config.py`
- Inspect: `src/trader/task/task_config.py`
- Inspect: `git diff`

- [ ] **Step 1: Review existing diff**

Run: `git diff -- src/trader/exchange/exchange_config.py src/trader/task/task_config.py`

Expected: shows earlier `account_id` and multi-account exchange config draft.

- [ ] **Step 2: Decide retention**

Keep only pieces that align with the new `user_id` ownership design. Do not preserve `account_id` as the primary domain concept unless it is explicitly mapped to `user_id` or exchange credential records.

- [ ] **Step 3: Add or revise tests in later tasks**

Do not commit this draft as-is. Fold it into Task 4 or Task 6 when owner-aware task creation and exchange routing are implemented.

---

## Task 1: Password Policy and Hashing

**Files:**
- Create: `src/trader/auth/__init__.py`
- Create: `src/trader/auth/passwords.py`
- Test: `tests/test_auth_passwords.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependencies**

Add `argon2-cffi` to `pyproject.toml`.

- [ ] **Step 2: Write failing password tests**

Test cases:
- valid passwords pass policy.
- too-short passwords fail.
- password equal to username fails.
- common weak passwords fail.
- password without letters or numbers fails.
- generated temporary password satisfies policy.
- hash verification succeeds with the right password and fails with the wrong password.

Run: `uv run python -m pytest tests/test_auth_passwords.py -v`

Expected: FAIL because `trader.auth.passwords` does not exist.

- [ ] **Step 3: Implement password helpers**

Implement:
- `validate_username(username: str) -> None`
- `validate_password(username: str, password: str) -> None`
- `generate_temporary_password() -> str`
- `hash_password(password: str) -> str`
- `verify_password(password: str, password_hash: str) -> bool`

Use Argon2 for hashing. Keep weak-password list small and local for first phase.

- [ ] **Step 4: Verify tests pass**

Run: `uv run python -m pytest tests/test_auth_passwords.py -v`

Expected: PASS.

---

## Task 2: Database Models and Repositories

**Files:**
- Modify: `src/trader/database/models.py`
- Modify: `src/trader/database/manager.py`
- Create: `src/trader/database/user.py`
- Create: `src/trader/database/exchange_credential.py`
- Create: `src/trader/database/strategy_config.py`
- Create: `src/trader/database/migrations/0003_users_auth_and_ownership.py`
- Test: `tests/test_user_repositories.py`

- [ ] **Step 1: Write failing repository tests**

Use in-memory SQLite via `Tortoise.init(config=build_tortoise_config("sqlite://:memory:"))`.

Test cases:
- create user with unique username.
- fetch user by username and id.
- update password hash and `must_change_password`.
- create/delete session.
- save and fetch exchange credential metadata.
- save and fetch strategy config metadata.

Run: `uv run python -m pytest tests/test_user_repositories.py -v`

Expected: FAIL because models/repositories do not exist.

- [ ] **Step 2: Add models**

Add:
- `UserModel`
- `SessionModel`
- `ExchangeCredentialModel`
- `StrategyConfigModel`

Add `user_id` to `TaskStateModel`, nullable during migration for legacy rows.

- [ ] **Step 3: Add migration**

Create migration `0003_users_auth_and_ownership.py`.

Schema requirements:
- `users.username` unique.
- `sessions.session_hash` unique.
- `exchange_credentials` unique on `(user_id, exchange, label)` or first-phase `(user_id, exchange)`.
- `strategy_configs.user_id` indexed.
- `tasks.user_id` nullable indexed.

- [ ] **Step 4: Add repositories**

Keep repositories focused. Do not put auth logic in ORM models.

- [ ] **Step 5: Wire manager**

Update `REQUIRED_TABLES` and initialize:
- `self.user`
- `self.exchange_credential`
- `self.strategy_config`

- [ ] **Step 6: Verify tests pass**

Run: `uv run python -m pytest tests/test_user_repositories.py tests/test_database_manager.py -v`

Expected: PASS.

---

## Task 3: Session Authentication Middleware and Current User Context

**Files:**
- Create: `src/trader/auth/sessions.py`
- Create: `src/trader/auth/context.py`
- Modify: `src/trader/rpc/auth.py`
- Modify: `src/trader/rpc/app.py`
- Test: `tests/test_auth_sessions.py`
- Test: `tests/test_rpc_session_auth.py`

- [ ] **Step 1: Write failing session helper tests**

Test cases:
- raw session tokens are random and not stored directly.
- token hashes are stable for lookup.
- expiry detects expired sessions.

Run: `uv run python -m pytest tests/test_auth_sessions.py -v`

Expected: FAIL.

- [ ] **Step 2: Implement session helpers**

Use `secrets.token_urlsafe` for session token generation and SHA-256 for lookup hashes.

- [ ] **Step 3: Write failing RPC auth tests**

Test cases:
- `/admin` redirects unauthenticated users to `/login`.
- `/login` remains public.
- authenticated user can access `/admin`.
- `must_change_password` user is redirected to `/change-password`.
- normal user cannot access `/admin/users`.
- admin can access `/admin/users`.

- [ ] **Step 4: Implement session middleware/dependencies**

Use an HTTP-only cookie, for example `chainer_session`.

Cookie requirements:
- `httponly=True`
- `samesite="lax"`
- `secure` configurable for production

- [ ] **Step 5: Keep Basic Auth out of target flow**

Do not add `BasicAuthMiddleware` in `start()`. Existing Basic Auth tests should be deleted or rewritten to test session auth.

- [ ] **Step 6: Verify tests pass**

Run: `uv run python -m pytest tests/test_auth_sessions.py tests/test_rpc_session_auth.py tests/test_rpc.py -v`

Expected: PASS.

---

## Task 4: Login, Register, Logout, Forced Password Change

**Files:**
- Create: `src/trader/rpc/api/auth.py`
- Create: `src/trader/rpc/templates/login.html`
- Create: `src/trader/rpc/templates/register.html`
- Create: `src/trader/rpc/templates/change_password.html`
- Modify: `src/trader/rpc/app.py`
- Modify: `src/trader/rpc/templates/base.html`
- Test: `tests/test_rpc_auth_flows.py`

- [ ] **Step 1: Write failing flow tests**

Test cases:
- registration creates a normal user.
- duplicate username is rejected.
- login sets session cookie.
- logout clears session cookie.
- forced password-change user cannot access task pages.
- change password clears `must_change_password`.

- [ ] **Step 2: Add routes and templates**

Page routes:
- `GET /login`
- `GET /register`
- `GET /change-password`

API or form routes:
- `POST /api/auth/login`
- `POST /api/auth/register`
- `POST /api/auth/logout`
- `POST /api/auth/change-password`

Use HTMX for form submission where it reduces custom JavaScript.

- [ ] **Step 3: Add bootstrap admin creation**

On DB startup, if no admin exists and config has bootstrap credentials, create admin.

- [ ] **Step 4: Verify tests pass**

Run: `uv run python -m pytest tests/test_rpc_auth_flows.py tests/test_rpc_session_auth.py -v`

Expected: PASS.

---

## Task 5: Admin User Management

**Files:**
- Create: `src/trader/rpc/api/admin_users.py`
- Create: `src/trader/rpc/templates/admin_users.html`
- Create: `src/trader/rpc/templates/partials/admin_users_table.html`
- Modify: `src/trader/rpc/app.py`
- Modify: `src/trader/rpc/templates/base.html`
- Test: `tests/test_admin_user_management.py`

- [ ] **Step 1: Write failing admin tests**

Test cases:
- admin can list users.
- normal user cannot list users.
- admin reset generates a temporary password.
- reset sets `must_change_password=True`.
- reset response shows temporary password once.
- disabled users cannot log in, if disabled status is included in first phase.

- [ ] **Step 2: Implement endpoints**

Routes:
- `GET /admin/users`
- `GET /api/admin/users`
- `POST /api/admin/users/{user_id}/reset-password`

Use HTMX partial refresh for the user table.

- [ ] **Step 3: Add template**

Follow current Bootstrap style, but keep controls dense and operational.

- [ ] **Step 4: Verify tests pass**

Run: `uv run python -m pytest tests/test_admin_user_management.py -v`

Expected: PASS.

---

## Task 6: Encrypted Exchange Credential Management

**Files:**
- Create: `src/trader/auth/credentials.py`
- Create: `src/trader/rpc/api/account.py`
- Create: `src/trader/rpc/templates/account.html`
- Create: `src/trader/rpc/templates/partials/exchange_credentials.html`
- Modify: `src/trader/common/config.py`
- Modify: `src/trader/rpc/app.py`
- Modify: `pyproject.toml`
- Test: `tests/test_exchange_credentials.py`

- [ ] **Step 1: Add dependency**

Add `cryptography` to `pyproject.toml`.

- [ ] **Step 2: Write failing crypto tests**

Test cases:
- missing `TRADER_SECRET_KEY` reports credentials unavailable.
- encrypted credential values do not contain plaintext.
- decrypt returns original value with the same service key.
- decrypt fails with the wrong service key.

- [ ] **Step 3: Implement credential helpers**

Use a stable derived Fernet key from `TRADER_SECRET_KEY`, or store `TRADER_SECRET_KEY` directly as a URL-safe base64 Fernet key if that is the chosen operational format. Document the exact expected format in `example.env`.

- [ ] **Step 4: Write failing account route tests**

Test cases:
- normal user can save own exchange credentials when service key exists.
- normal user cannot read plaintext secret back.
- response masks API key.
- missing service key prevents save.
- user cannot mutate another user's credentials.

- [ ] **Step 5: Implement account page and endpoints**

Routes:
- `GET /account`
- `GET /api/account/exchange-credentials`
- `POST /api/account/exchange-credentials`
- `DELETE /api/account/exchange-credentials/{id}`

Use HTMX for save/delete and partial refresh. Alpine may be used only for local show/hide state.

- [ ] **Step 6: Verify tests pass**

Run: `uv run python -m pytest tests/test_exchange_credentials.py -v`

Expected: PASS.

---

## Task 7: Task Ownership Boundary

**Files:**
- Modify: `src/trader/task/task_config.py`
- Modify: `src/trader/task/task_manager.py`
- Modify: `src/trader/database/task.py`
- Modify: `src/trader/rpc/api/tasks.py`
- Modify: `src/trader/rpc/api/task.py`
- Modify: `src/trader/rpc/models.py`
- Test: `tests/test_task_ownership.py`

- [ ] **Step 1: Write failing ownership tests**

Test cases:
- task created by user A persists with user A ownership.
- user A task list does not include user B tasks.
- user A cannot fetch/close/delete user B task.
- admin can list all tasks or use an explicit platform view.
- legacy tasks with null `user_id` are visible only to admin or handled by a documented migration rule.

- [ ] **Step 2: Attach current user to task creation**

The API layer should attach the authenticated user's id to task configs before calling `send_add_tasks_msg`.

- [ ] **Step 3: Persist owner**

Update `TaskState` persistence path so `TaskStateModel.user_id` is saved.

- [ ] **Step 4: Filter query APIs**

Update task repository and RPC models to accept current-user context.

- [ ] **Step 5: Verify tests pass**

Run: `uv run python -m pytest tests/test_task_ownership.py tests/test_rpc.py -v`

Expected: PASS.

---

## Task 8: Live Task Credential Routing

**Files:**
- Modify: `src/trader/task/task_manager.py`
- Modify: `src/trader/app/app.py`
- Modify: `src/trader/exchange/exchange_config.py`
- Modify: `src/trader/rpc/api/live.py`
- Test: `tests/test_live_task_user_routing.py`

- [ ] **Step 1: Write failing routing tests**

Test cases:
- live task for user A builds exchange config from user A credential.
- live task for user B builds exchange config from user B credential.
- missing credential blocks live task start with a clear error.
- missing `TRADER_SECRET_KEY` blocks live task start with a clear error.
- non-live data/backtest tasks do not require user exchange credentials unless they submit live orders.

- [ ] **Step 2: Replace global exchange dependency for live tasks**

Keep public market-data paths compatible, but live order submission must route through the task owner's credential.

- [ ] **Step 3: Reconcile previous multi-account draft**

If `parse_multi_account_exchange_config` is still useful for CLI compatibility, keep it as a legacy config parser. Do not let it bypass user-owned encrypted credentials for web-created live tasks.

- [ ] **Step 4: Filter live APIs**

`/api/live/strategies` and live snapshot/event routes must reject access to another user's live task unless the user is admin.

- [ ] **Step 5: Verify tests pass**

Run: `uv run python -m pytest tests/test_live_task_user_routing.py tests/test_realtime_live_runtime.py -v`

Expected: PASS.

---

## Task 9: Strategy Configs and Task Center UX

**Files:**
- Create: `src/trader/rpc/api/strategy_configs.py`
- Create: `src/trader/rpc/templates/strategy_configs.html`
- Create: `src/trader/rpc/templates/partials/strategy_config_form.html`
- Create: `src/trader/rpc/templates/partials/task_create_form.html`
- Modify: `src/trader/rpc/templates/tasks.html`
- Modify: `src/trader/rpc/app.py`
- Test: `tests/test_strategy_config_ui.py`

- [ ] **Step 1: Write failing strategy config tests**

Test cases:
- user can create strategy config.
- user can list own strategy configs.
- user cannot see another user's strategy configs.
- user can create a backtest task from a strategy config.
- user can create a live task from a strategy config only when credentials are ready.

- [ ] **Step 2: Implement repository/API usage**

Use `StrategyConfigModel` from Task 2.

- [ ] **Step 3: Add pages**

Routes:
- `GET /strategies`
- `GET /tasks`

The task page should become task center, with raw JSON moved to an advanced/debug section.

- [ ] **Step 4: Use HTMX for partial updates**

Use HTMX for:
- strategy config form submission.
- task create modal loading.
- task list refresh.
- task type filtering where server filtering is preferred.

- [ ] **Step 5: Verify tests pass**

Run: `uv run python -m pytest tests/test_strategy_config_ui.py tests/test_rpc.py -v`

Expected: PASS.

---

## Task 10: Task-Type-Specific Detail Views

**Files:**
- Create: `src/trader/rpc/templates/partials/task_detail_backtest.html`
- Create: `src/trader/rpc/templates/partials/task_detail_live.html`
- Create: `src/trader/rpc/templates/partials/task_detail_data.html`
- Create: `src/trader/rpc/templates/partials/task_detail_optimization.html`
- Modify: `src/trader/rpc/templates/tasks.html`
- Modify: `src/trader/rpc/api/task.py`
- Test: `tests/test_task_detail_views.py`

- [ ] **Step 1: Write failing detail view tests**

Test cases:
- backtest task detail renders backtest metrics.
- live task detail renders live-specific state placeholders.
- data task detail renders data coverage/progress placeholders.
- optimization task detail renders optimization progress placeholders.
- access control applies to each detail path.

- [ ] **Step 2: Implement HTMX detail route**

Add a route that returns an HTML partial based on task type.

- [ ] **Step 3: Reduce handwritten JS**

Replace existing modal fetch/string-template logic in `tasks.html` with HTMX partial loading where feasible.

- [ ] **Step 4: Verify tests pass**

Run: `uv run python -m pytest tests/test_task_detail_views.py -v`

Expected: PASS.

---

## Task 11: Documentation and Configuration

**Files:**
- Modify: `README.md`
- Modify: `example.env`
- Modify: `docs/architecture/database-design.md`
- Modify: `docs/superpowers/specs/2026-05-15-multi-user-admin-and-task-console-design.md`

- [ ] **Step 1: Document new environment variables**

Document:
- `TRADER_AUTH_USERNAME`
- `TRADER_AUTH_PASSWORD`
- `TRADER_SECRET_KEY`
- session cookie/security settings if added.

- [ ] **Step 2: Document bootstrap behavior**

Make clear that configured auth credentials create only the first admin and do not remain the normal login source after DB bootstrap.

- [ ] **Step 3: Document credential encryption**

Explain backup requirements for `TRADER_SECRET_KEY`: losing it means encrypted exchange credentials cannot be decrypted.

- [ ] **Step 4: Update database design docs**

Add user/session/credential/strategy/task ownership tables and relationships.

---

## Task 12: Verification Pass

**Files:**
- No new files.

- [ ] **Step 1: Run targeted auth and ownership tests**

Run:
`uv run python -m pytest tests/test_auth_passwords.py tests/test_auth_sessions.py tests/test_rpc_session_auth.py tests/test_rpc_auth_flows.py tests/test_admin_user_management.py tests/test_exchange_credentials.py tests/test_task_ownership.py -v`

Expected: PASS.

- [ ] **Step 2: Run affected RPC and task tests**

Run:
`uv run python -m pytest tests/test_rpc.py tests/test_cli_task_handling.py tests/test_live_monitor_api_contract.py tests/test_realtime_live_runtime.py -v`

Expected: PASS.

- [ ] **Step 3: Run full suite if runtime context is complete**

Before running, follow repository context gate. If Python environment or DB context is incomplete, stop and surface the exact blocker.

Run:
`uv run python -m pytest`

Expected: PASS or documented external-context skips only.

- [ ] **Step 4: Manual browser smoke**

Start the API locally and verify:
- unauthenticated redirect to login.
- register/login/logout.
- admin user page.
- reset password flow.
- forced password change.
- account credential page with missing and present `TRADER_SECRET_KEY`.
- task center task list filtering.
- live monitor access control.

---

## Commit Guidance
Prefer one commit per task or per small group of tightly related tasks:

- `feat: add password hashing helpers`
- `feat: add user auth schema`
- `feat: add session login flow`
- `feat: add admin user management`
- `feat: add encrypted exchange credentials`
- `feat: scope tasks to users`
- `feat: route live tasks by user credentials`
- `feat: add strategy config task center`
- `docs: document multi-user console setup`

Do not commit secrets, generated local DB files, or test output artifacts.
