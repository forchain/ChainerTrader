# Task-scoped open-order cleanup

We decided to stop auto-canceling every open exchange order when starting or stopping a task. Instead, task lifecycle cleanup should target only the open orders that belong to running tasks for the same account, using persisted task-order linkage where available.

The account page exposes symbol-scoped open-order visibility and a manual cancellation action with the same explicit target. It must not default to listing all account open orders, infer cancellation targets from locked balances, or issue account-wide cancellation. A user must enter a concrete symbol such as `SOLUSDT`; the page previews that symbol's current open orders and then cancels only that symbol. This replaces the previous `TRADER_LIVE_ORDER_CLEANUP_SYMBOLS` account-page behavior, which was operationally fragile because the list could be either too broad or incomplete.
