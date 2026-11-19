# src/trader/AGENTS.md

`src/trader/` is the home for reusable application logic.

Rules:
- New reusable modules belong here
- New business rules and use cases belong under `src/trader/core/<bounded-context>/...`
- New inbound or outbound integrations belong under `src/trader/adapters/{inbound,outbound}/...`
- `src/trader/core/` must not import `trader.adapters` or FastAPI, Tortoise, backtrader, ccxt, or Binance SDKs (ADR-0003)
- New CLI modules should go under `src/trader/adapters/inbound/cli/...` when they are product-facing entry points
- New reusable operational, reporting, or repository helpers should live in the bounded-context package they serve (`src/trader/core/<bounded-context>/...`); filesystem-backed report helpers belong under `src/trader/adapters/outbound/files/...`
- Do not push reusable logic back into `scripts/` for convenience
