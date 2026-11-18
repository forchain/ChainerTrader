# Architecture Decision Records

Index of durable architectural decisions for ChainerTrader:

- [ADR-0001: Task-scoped open order cleanup](0001-task-scoped-open-order-cleanup.md) — Limits automatic open-order cancellation to orders belonging to the starting or stopping task.
- [ADR-0002: Startup mode split](0002-startup-mode-split.md) — Separates API mode (persisted RUNNING-task recovery) from console mode (one-shot startup execution without recovery).
- [ADR-0003: Hexagonal layering for the trading core](0003-hexagonal-layering.md) — Organizes domain and application rules under `src/trader/core/`, inbound/outbound adapters under `src/trader/adapters/`, and wires concrete implementations solely in the composition root (`src/trader/main.py`).
