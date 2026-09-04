# configs/AGENTS.md

`configs/` stores non-executable configuration assets only.

Rules:
- Put task JSON files under `configs/tasks/...`
- Put notice JSON files under `configs/notices/...`
- Do not add Python modules or shell scripts here
- If a config needs a runner or parser, place that logic under `src/trader/...` or a thin wrapper in `scripts/`
