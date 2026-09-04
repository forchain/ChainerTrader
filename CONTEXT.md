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

**手动取消冻结资产开放订单**:
An account-page emergency action that cancels open orders only for symbols inferred from balances with `locked > 0`, using the current task symbol when a locked quote asset needs a concrete pair.
_Avoid_: Global cleanup, auto-cancel, cancel all account orders, configured cleanup symbols

**API模式**:
An API-first runtime mode that keeps the FastAPI service alive after startup.
_Avoid_: Server mode, web mode

**console模式**:
A one-shot runtime mode that runs startup work and then exits.
_Avoid_: CLI mode, batch mode

**候选币种集合**:
A curated set of market symbols that a backtest or optimization run may expand into executable tasks.
_Avoid_: Watchlist, coin list, symbol list

**任务模板**:
A reusable task definition that fixes non-symbol parameters while leaving the candidate symbols to be injected by a generator.
_Avoid_: Preset, sample config

**选币结果任务配置**:
A concrete task file generated from optimization rankings, containing the selected symbols and their winning strategy parameters.
_Avoid_: Top list, portfolio file
