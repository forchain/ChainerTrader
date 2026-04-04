## Why

在 git worktree 中开发时，`.venv` 和 `.env` 不会从主仓库复制过来，导致：
1. `uv run` 找不到 Python 虚拟环境，所有命令执行失败
2. `python-dotenv` 加载不到环境变量（`TRADER_DB`、`TRADER_LOG_LEVEL` 等），运行时报错

这个问题对 Agent 尤其严重——Agent 在 worktree 中启动后，第一条命令就会失败，无法自行恢复。需要一个幂等的自动化脚本让 worktree 环境一键可用，并在 CLAUDE.md 中告知 Agent 在检测到 worktree 环境异常时主动执行该脚本。

## What Changes

- **新增** `scripts/setup_worktree.sh`：幂等的 worktree 环境恢复脚本
  - 通过 `.git` 文件（非目录）检测是否处于 worktree
  - 从 `.git` 文件内容解析主仓库路径
  - 创建 `.venv` → 主仓库 `.venv` 的 symlink
  - 创建 `.env` → 主仓库 `.env` 的 symlink（如果主仓库有 `.env`）
  - 多次运行安全，已存在的 symlink 不会重复创建
- **修改** `CLAUDE.md`：新增 "Worktree Development" 部分，指示 Agent 检测 worktree 环境并在必要时自动执行脚本

## Capabilities

### New Capabilities

- `worktree-env-setup`：一键恢复 worktree 开发环境，通过 symlink 共享主仓库的 `.venv` 和 `.env`

### Modified Capabilities

- （无）

## Impact

- **`scripts/setup_worktree.sh`**：新增文件，不影响现有功能
- **`CLAUDE.md`**：新增 Agent 行为指引，不影响代码逻辑
