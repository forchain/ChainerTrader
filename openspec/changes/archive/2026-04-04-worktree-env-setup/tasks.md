## 1. 创建 setup_worktree.sh 脚本

- [x] 1.1 创建 `scripts/setup_worktree.sh`，实现 worktree 检测（`.git` 是文件而非目录）
- [x] 1.2 实现主仓库路径解析（从 `.git` 文件内容提取 `gitdir`，反推主仓库根目录）
- [x] 1.3 实现 `.venv` symlink 创建（检查主仓库 `.venv` 存在性，检查当前 symlink 状态，创建或跳过）
- [x] 1.4 实现 `.env` symlink 创建（主仓库 `.env` 存在时创建，不存在时 warning 跳过）
- [x] 1.5 添加验证步骤（检查 `.venv/bin/python` 可通过 symlink 访问）
- [x] 1.6 添加 `chmod +x`，在当前 worktree 中测试脚本执行

## 2. 更新 CLAUDE.md

- [x] 2.1 在 CLAUDE.md 中添加 "Worktree Development" section
- [x] 2.2 包含 Agent 自动检测和执行指令：检测条件（`.git` 是文件 AND `.venv` 不存在）、执行命令（`bash scripts/setup_worktree.sh`）、执行时机（在其他操作之前）

## 3. 验证

- [x] 3.1 在当前 worktree 中运行脚本，验证 symlink 正确创建
- [x] 3.2 验证 `uv run python -c "import trader; print('ok')"` 在 worktree 中可执行
- [x] 3.3 验证脚本幂等性（再次运行不会报错或重复创建）
