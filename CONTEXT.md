# ChainerTrader Domain Language

This repository manages trading tasks, their exchange orders, and the account-facing views that explain balance usage and live order state.

## Language

**任务**:
A persisted trading or data-processing unit with its own runtime state, configuration snapshot, and task ID.
_Avoid_: Job, run

**运行中任务**:
A task whose runtime state is active and whose exchange activity is still live.
_Avoid_: Active job, live job

**执行状态记录**:
A persisted record for one order intent or exchange-order outcome, including the owning `task_id`.
_Avoid_: Order log, event, trade record

**开放订单**:
An exchange-side order that is still active and not yet terminal.
_Avoid_: Pending order, unfinished order

**锁定来源**:
The account-page view that explains which open orders are locking balance.
_Avoid_: Lock reason, frozen source

**手动取消清理币种开放订单**:
An account-page emergency action that cancels open orders only for symbols configured by `TRADER_LIVE_ORDER_CLEANUP_SYMBOLS`.
_Avoid_: Global cleanup, auto-cancel, cancel all account orders

**API模式**:
An API-first runtime mode that keeps the FastAPI service alive after startup.
_Avoid_: Server mode, web mode

**console模式**:
A one-shot runtime mode that runs startup work and then exits.
_Avoid_: CLI mode, batch mode
