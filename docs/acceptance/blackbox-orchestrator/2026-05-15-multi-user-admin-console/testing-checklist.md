# Testing Checklist

Status values: `pending`, `in_progress`, `passed`, `failed`, `blocked`, `reopened`, `skipped_force_majeure`.

## Required Items

### BB-001 Session Auth Gate
- Status: passed
- Purpose: prove protected admin pages use session login instead of browser Basic Auth.
- Setup: server app with bootstrap admin credentials and initialized user store.
- Steps:
  1. Request `/admin` without session.
  2. Request `/login`.
  3. Submit valid login credentials.
  4. Request `/admin` with returned session cookie.
- Expected: unauthenticated request redirects to `/login`; login page is HTML; login returns session cookie; authenticated `/admin` returns HTML without `WWW-Authenticate: Basic`.
- Evidence fields: HTTP statuses, response headers, cookie name, redirect location.

### BB-002 Registration And Password Policy
- Status: passed
- Purpose: prove normal users can self-register without email while weak credentials are rejected.
- Setup: initialized user store.
- Steps:
  1. POST `/register` with too-short username/password.
  2. POST `/register` with valid username/password.
  3. Login with the registered account.
- Expected: weak registration is rejected with 4xx; valid registration redirects to login; login succeeds and creates a session.
- Evidence fields: HTTP statuses, redirect locations, cookie presence.

### BB-003 Admin Reset Forces Password Change
- Status: passed
- Purpose: prove administrator reset creates a temporary password and forces user password update before accessing admin pages.
- Setup: one admin session and one normal user.
- Steps:
  1. Admin posts `/admin/users/{user_id}/reset-password`.
  2. Extract temporary password from returned HTML.
  3. Login as user with temporary password.
  4. Request `/admin` with that session.
  5. POST `/change-password` with a new valid password.
  6. Login with the new password and request `/admin`.
- Expected: reset page displays a temporary password; user is redirected to `/change-password` until password is changed; new password allows normal access.
- Evidence fields: HTTP statuses, redirect locations, temporary password presence, final page status.

### BB-004 Account Credential Service-Key Gate
- Status: passed
- Purpose: prove missing `TRADER_SECRET_KEY` allows login/pages but blocks API-key save.
- Setup: authenticated normal user with app config missing service key.
- Steps:
  1. GET `/account`.
  2. POST `/account/exchange-credentials` with Binance key and secret.
- Expected: account page returns HTML and shows service-key warning; save returns 503 and does not show plaintext key/secret.
- Evidence fields: HTTP status, warning text, plaintext absence.

### BB-005 Account Credential Save With Service Key
- Status: passed
- Purpose: prove users can save their own exchange API key when service key exists and UI only shows a masked key.
- Setup: authenticated normal user with `TRADER_SECRET_KEY` configured.
- Steps:
  1. POST `/account/exchange-credentials` with Binance key and secret.
  2. GET `/account`.
- Expected: save redirects to `/account`; account page shows masked API key; plaintext secret is absent.
- Evidence fields: HTTP status, redirect location, masked key, plaintext absence.

### BB-006 Task Ownership Over HTTP API
- Status: passed
- Purpose: prove tasks created through the public task API are assigned to the current user and normal users cannot see each other's tasks.
- Setup: two normal user sessions and one admin session.
- Steps:
  1. User A posts `/api/tasks` with a DEBUG task JSON.
  2. User B posts `/api/tasks` with a DEBUG task JSON.
  3. User A gets `/api/tasks`.
  4. User B gets `/api/tasks`.
  5. Admin gets `/api/tasks`.
- Expected: each normal user sees only their task; admin sees both.
- Evidence fields: HTTP statuses, task IDs, user IDs if exposed, response counts.

### BB-007 Live Monitor Ownership
- Status: blocked
- Purpose: prove live monitor lists/snapshots are scoped to the task owner.
- Setup: observable running live-task-like entries owned by two different users and one admin session.
- Steps:
  1. User A GETs `/api/live/strategies`.
  2. User B GETs `/api/live/strategies`.
  3. Admin GETs `/api/live/strategies`.
  4. User A attempts snapshot for User B's live strategy.
- Expected: each normal user sees only owned strategy; admin sees both; cross-user snapshot returns 404.
- Evidence fields: HTTP statuses, visible strategy IDs, response counts.

### BB-008 User-Owned Live Credential Routing Failure Modes
- Status: passed
- Purpose: prove user-owned live trading cannot start without the service key or user Binance credential.
- Setup: public task-start path or operator-equivalent task launch flow.
- Steps:
  1. Attempt user-owned live task launch without `TRADER_SECRET_KEY`.
  2. Attempt user-owned live task launch with service key but without saved credential.
  3. Attempt launch with service key and saved credential using test exchange/harness.
- Expected: first two attempts fail clearly; third routes to a user credential without exposing plaintext in public output.
- Evidence fields: command/API path, error text, success indicator, plaintext absence.

### BB-009 Admin API Authorization
- Status: passed
- Purpose: prove platform-level admin API is unavailable to normal users.
- Setup: one normal user session and one admin session.
- Steps:
  1. Normal user GETs `/api/admin/users`.
  2. Admin GETs `/api/admin/users`.
- Expected: normal user receives 403; admin receives user list.
- Evidence fields: HTTP statuses, response fields.

### BB-010 Documentation And CLI Surface Consistency
- Status: passed
- Purpose: prove operator-facing docs/examples no longer instruct Basic Auth as the active model and document service-key behavior.
- Setup: current worktree.
- Steps:
  1. Inspect README/example env/agent guidance from user-visible files.
  2. Run CLI help if feasible.
- Expected: docs mention session login/bootstrap admin and `TRADER_SECRET_KEY`; no active examples instruct `curl -u`, `HTTP Basic Auth`, or Basic Auth protected-path deployment.
- Evidence fields: grep output, CLI help excerpt, file paths.
