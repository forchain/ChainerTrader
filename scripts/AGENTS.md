# scripts/AGENTS.md

`scripts/` is for operational shell scripts and thin compatibility wrappers.

Rules:
- Do not add task JSON or notice JSON files here
- Do not add reusable business logic here
- If Python logic is testable or reusable, move it under `src/trader/...`
- Keep wrappers thin and focused on argument parsing, process launching, or repo operations
