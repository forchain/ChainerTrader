# src/trader/AGENTS.md

`src/trader/` is the home for reusable application logic.

Rules:
- New reusable modules belong here
- New CLI modules should go under `src/trader/cli/...` when they are product-facing entry points
- New reusable operational, reporting, or repository helpers should go under `src/trader/tools/...`
- Do not push reusable logic back into `scripts/` for convenience
