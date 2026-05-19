# Multi-User Admin and Task Console Design

## Status
Draft

## Date
2026-05-15

## Context
ChainerTrader currently has a single-user web console protected by optional Basic Auth. The console can create tasks, inspect task history, and view live strategy monitoring, but its information architecture still reflects an early development/debugging tool:

- API credentials are configured globally at the server level.
- Basic Auth protects pages but does not model users, roles, sessions, registration, password reset, or resource ownership.
- Live trading is presented as its own monitoring area, even though it is conceptually one task type.
- The task UI accepts raw JSON, which is useful for debugging but not suitable as the main workflow for normal users.
- Strategy configuration, task execution, live monitoring, data jobs, and platform administration are not clearly separated.

The next stage should introduce account isolation while keeping the first implementation simple and compatible with the existing FastAPI, Jinja, Bootstrap, and lightweight JavaScript stack.

## Goals
- Support an administrator account and normal user accounts.
- Let each normal user manage their own exchange API credentials.
- Let each normal user manage their own strategy configurations and task runs.
- Treat live trading as an important task type, not as a separate execution system.
- Keep the first-phase frontend server-rendered with FastAPI + Jinja + Bootstrap.
- Remove Basic Auth from the target architecture once database-backed login is available.
- Preserve the ability to adopt React, Vue, or Svelte later for complex pages without requiring a full backend rewrite.

## Non-Goals
- Email verification.
- Password recovery by email.
- A full SPA rewrite.
- A separate frontend production server.
- Multi-tenant billing, teams, organizations, or delegated permissions.
- Administrator access to plaintext user exchange secrets.

## Recommended First-Phase Architecture

### Authentication
Use database-backed username/password login with HTTP-only cookie sessions.

The existing configuration fields for auth username/password become bootstrap administrator credentials:

- On first startup, if no administrator exists, create one from the configured username/password.
- After an administrator exists in the database, database state becomes the source of truth.
- The configured credentials should not overwrite an existing administrator password.

Basic Auth should be removed from the target user flow because it cannot represent registration, logout, roles, forced password changes, or per-user resource isolation.

### Roles
Use two roles in the first phase:

- `admin`: platform management, user management, password resets, platform-level data.
- `user`: own strategy configs, own tasks, own live monitoring, own API credentials, own password.

Avoid more granular permissions until the product needs them.

### Password Flow
Keep the password workflow closed inside the platform:

- Registration does not require email verification.
- Users cannot self-serve password recovery.
- Administrators can reset a user's password.
- Reset generates a random temporary password.
- After login with a temporary password, the user is forced to change it before accessing normal pages.

Password rules should be basic but meaningful:

- Username length: 3-32 characters.
- Username characters: letters, numbers, underscore, hyphen.
- Password length: at least 10 characters.
- Password must not equal the username.
- Password must not be a known weak password.
- Password must contain at least letters and numbers.

Passwords must be stored with a password hashing algorithm such as Argon2 or bcrypt.

### Exchange API Credentials
Each user can store their own exchange API credentials.

The database must not store plaintext exchange secrets. Store encrypted API keys and encrypted API secrets. A service-level secret such as `TRADER_SECRET_KEY` is used to encrypt and decrypt user exchange credentials.

If `TRADER_SECRET_KEY` is missing:

- Login and read-only pages may still work.
- Saving exchange credentials must be disabled.
- Starting live trading tasks must be disabled because credentials cannot be safely decrypted.

This secret is not a user's exchange API key. It is the server-side encryption key for the credential vault.

### Core Domain Model
Introduce these first-phase entities:

- `User`: account identity, role, password hash, status, forced password-change flag.
- `Session`: server-side session linked to a user.
- `ExchangeCredential`: encrypted exchange API credentials owned by a user.
- `StrategyConfig`: reusable strategy setup owned by a user.
- `TaskRun`: one execution instance owned by a user.
- `LiveRuntimeState`: runtime state for live task monitoring.

The existing task state model can be evolved instead of replaced immediately, but task records must gain user ownership.

## Information Architecture
Use these top-level console sections:

- Overview
- Strategy Management
- Task Center
- Live Monitoring
- Data Management
- My Account
- Platform Management

`Platform Management` is visible to administrators only.

### Strategy Management
Strategy management answers: "What do I want to run?"

It manages reusable strategy configurations:

- Strategy template/name.
- Symbol and interval.
- Strategy parameters.
- Risk and execution settings.
- Default live/backtest settings.

Raw JSON should remain available as an advanced/debug path, but it should not be the primary user workflow.

### Task Center
Task center answers: "How do I want to run it?"

Each run is a task instance:

- `backtest`
- `live`
- `data_download`
- `check_klines`
- `optimization`

Users should be able to create a task from a saved strategy configuration, select the task type, adjust task-specific options, and start it.

Task detail pages should differ by task type:

- Backtest: report, metrics, trades, equity curve.
- Live: status, current position, latest signal, orders, risk events, controls.
- Data download: progress, coverage, missing ranges, retry/error details.
- Optimization: sample matrix, progress, best parameters, failed samples.

### Live Monitoring
Live monitoring is a specialized view over `TaskRun` records where `task_type = live`.

It should not own task creation. It should display and control live task runtime state:

- Running live tasks.
- Position.
- Signals.
- Orders.
- Risk events.
- Recent execution logs.

### My Account
Normal users can:

- Change password.
- Manage exchange API credentials.
- Review account-level settings.

### Platform Management
Administrators can:

- View users.
- Create or disable users if needed.
- Reset user passwords.
- View platform-level task and runtime data.
- View system configuration status without exposing secrets.

## Authorization Rules
- Unauthenticated users can access only login, registration, health checks, and static assets.
- Users with `must_change_password = true` can access only logout and change-password flows.
- Normal users can read and mutate only their own strategy configs, credentials, tasks, and live runtime views.
- Administrators can view platform-level data and manage users.
- API routes must enforce authorization, not only page routes.
- Public market data such as K-lines can remain shared, but any user-specific task or live state must be filtered by user ownership.

## Frontend Direction
First phase should keep the current stack:

- FastAPI routes.
- Jinja templates.
- Bootstrap.
- Minimal handwritten JavaScript.

Optional lightweight enhancements:

- HTMX is the primary enhancement for server-backed interactions: form submission, pagination, modal content loading, table refreshes, task status refreshes, and other partial HTML updates.
- Alpine.js is optional and limited to local UI state: expand/collapse controls, small tabs, field visibility, copy-button state, and other interactions that do not need to fetch or replace server-rendered data.

Use a clear ownership rule:

- If the interaction changes or reloads server data, use HTMX and return a Jinja-rendered partial.
- If the interaction only changes local display state, use Alpine.js.
- Avoid letting HTMX and Alpine.js control the same DOM subtree.

React, Vue, or Svelte can be adopted later for complex pages. The recommended future migration shape is not a separate production frontend server, but compiled static frontend assets served by FastAPI. Good candidates for future component frameworks:

- Strategy parameter editor.
- Live monitoring workbench.
- Backtest report explorer.
- Optimization workbench.

Avoid a full SPA rewrite in the first phase because the domain model and console workflows are still being clarified.

## Migration Strategy
Implement in phases:

1. Authentication foundation.
   - Add users and sessions.
   - Bootstrap administrator from config.
   - Add login, register, logout, forced password change.
   - Remove Basic Auth from the target runtime path.

2. Ownership boundaries.
   - Add user ownership to task records.
   - Filter task APIs and pages by current user.
   - Give administrators platform-level views.

3. Credential management.
   - Add encrypted per-user exchange credentials.
   - Require `TRADER_SECRET_KEY` for saving credentials and live trading.
   - Route live tasks to the owning user's credentials.

4. Strategy configuration.
   - Add saved strategy configurations.
   - Let users create task runs from saved configs.
   - Keep raw JSON as an advanced/debug interface.

5. Task-type-specific UI.
   - Split task center views by task type.
   - Keep live monitoring as a filtered, specialized view of live task runs.

## Risks
- Retrofitting ownership into existing task state can miss an API path if authorization is not applied consistently.
- Encrypting credentials requires operational discipline around `TRADER_SECRET_KEY` backup and rotation.
- Removing Basic Auth before session auth is complete can expose the console.
- Trying to redesign the full frontend while changing the domain model would increase scope and slow delivery.

## Open Decisions
- Whether registration is public or administrator-created only in the first release.
- Whether users can have multiple exchange credentials per exchange or only one default credential.
- Whether administrator can view all task logs or only sanitized platform-level events.
- Whether `TaskRun` should be a new table or an evolution of the existing `tasks` table.
