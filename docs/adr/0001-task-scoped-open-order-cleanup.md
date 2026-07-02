# Task-scoped open-order cleanup

We decided to stop auto-canceling every open exchange order when starting or stopping a task. Instead, task lifecycle cleanup should target only the open orders that belong to running tasks for the same account, using persisted task-order linkage where available. The account page will expose a manual action that cancels open orders only for symbols configured by `TRADER_LIVE_ORDER_CLEANUP_SYMBOLS`, plus a full open-order list for visibility; account-wide cancellation is too broad for normal task lifecycle handling.
