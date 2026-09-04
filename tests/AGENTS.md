# tests/AGENTS.md

`tests/` is for automated verification only.

Rules:
- Prefer testing `src/trader/...` modules instead of `scripts/...`
- Place fixtures under `tests/fixtures/...`
- Do not commit generated runtime artifacts under `tests/output/`
- When adding regression coverage for refactors, prove behavior, not directory trivia
