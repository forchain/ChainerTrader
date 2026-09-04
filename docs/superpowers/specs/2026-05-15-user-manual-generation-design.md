# User Manual Generation Design - Multi-User Admin Console

## Status
Draft

## Date
2026-05-15

## Context
The recent PR (Multi-User Admin Console) introduced significant architectural changes:
- Transition from single-user to multi-user support.
- Database-backed session authentication (FastAPI + Jinja + Cookies).
- Role-based access control (Admin vs. User).
- Encrypted storage for per-user Exchange API Credentials.
- Resource ownership for Strategy Configs and Task Runs.

A user manual is required to guide both traders and administrators through these new workflows.

## Goals
- Create a comprehensive `docs/user-manual.md` that covers all new features.
- Provide clear, role-based instructions for Traders and Administrators.
- Integrate the manual into the existing MkDocs navigation.
- Use clear, actionable Chinese language suitable for the target audience.

## Non-Goals
- Documenting internal code implementation (covered in technical docs).
- Documenting deprecated Basic Auth flows.
- Multi-language support (Chinese only for now).

## Content Structure (Role-Based)

### 1. Introduction
- Overview of the Multi-User Admin Console.
- Access URL and basic security concepts (Encrypted credentials, session safety).

### 2. Trader's Guide (交易员指南)
- **Account Management**: Registration, Login, and Password Change.
- **Exchange Credentials**: Adding and managing encrypted API keys for exchanges (Binance, etc.).
- **Strategy Management**: Creating and saving reusable strategy configurations.
- **Task Center**:
    - Launching Backtests and Live tasks.
    - Monitoring task status and real-time logs.
    - Understanding task-specific dashboards (Performance metrics vs. Live monitoring).

### 3. Administrator's Guide (管理员指南)
- **Bootstrapping**: Setting up the initial administrator via environment variables (`ADMIN_USER`, `ADMIN_PASSWORD`).
- **User Management**: Viewing user lists and performing password resets.
- **System Monitoring**: Overseeing platform-wide task execution and system health.
- **Security Best Practices**: Managing `TRADER_SECRET_KEY` for vault encryption.

## Integration Plan
- **File Location**: `docs/user-manual.md`
- **MkDocs Update**:
    - Modify `mkdocs.yml` to include the manual in the navigation.
    - Example:
      ```yaml
      nav:
        - Home: index.md
        - 用户手册: user-manual.md
      ```

## Implementation Strategy
1.  **Drafting**: Write the content based on the analyzed code and design specs of the Multi-User PR.
2.  **Validation**: Verify that all UI elements described (registration, credential forms, etc.) match the implementation in `src/trader/rpc/templates/`.
3.  **Finalization**: Integrate into `mkdocs.yml`.

## Risks
- **Desynchronization**: UI changes in the future may require manual updates to this doc.
- **Encryption Confusion**: Users might confuse the server secret (`TRADER_SECRET_KEY`) with their own API secrets. Clarification is needed in the manual.
