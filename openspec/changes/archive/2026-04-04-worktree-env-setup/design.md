## Architecture

```
scripts/setup_worktree.sh
│
├── 1. DETECT: .git is a file? → we're in a worktree
│
├── 2. RESOLVE: parse .git file → extract main repo path
│   .git content: "gitdir: /path/to/.git/worktrees/<name>"
│   strip "/.git/worktrees/<name>" → main repo root
│
├── 3. SYMLINK .venv
│   if .venv missing or broken symlink:
│     ln -sfn $MAIN_REPO/.venv .venv
│
├── 4. SYMLINK .env
│   if main repo has .env AND worktree .env missing:
│     ln -sfn $MAIN_REPO/.env .env
│
└── 5. VERIFY: check .venv/bin/python exists via symlink
```

## Key Decisions

### Symlink vs Copy vs uv sync
选择 symlink 而非 copy 或 `uv sync`：
- symlink 是零成本的（没有额外磁盘占用，没有安装时间）
- 所有 worktree 共享同一个 `.venv`，无需维护多份
- `uv run` 和 `python-dotenv` 透明支持 symlink，无需任何配置

### 主仓库路径解析
通过 `.git` 文件内容反推主仓库路径：
```bash
GITDIR=$(sed 's/^gitdir: //' .git)
MAIN_REPO=$(echo "$GITDIR" | sed 's|/\.git/worktrees/.*||')
```
这是 git worktree 的标准机制，可靠且不依赖特定目录结构。

### 幂等性
脚本多次运行安全：
- 已存在的有效 symlink → 跳过
- 已存在但 broken 的 symlink → 重新创建
- 不在 worktree 中运行 → 提示并退出（exit 0，不报错）

### Agent 集成
在 CLAUDE.md 中添加明确指令：
- 检测条件：`.git` 是文件 AND `.venv` 不存在
- 动作：执行 `bash scripts/setup_worktree.sh`
- 时机：在任何其他操作之前

## Error Handling

| 场景 | 行为 |
|------|------|
| 不在 worktree 中 | 打印提示，exit 0 |
| 主仓库 `.venv` 不存在 | 报错提示先在主仓库运行 `make install`，exit 1 |
| 主仓库 `.env` 不存在 | 跳过 `.env` symlink（不是必需的），打印 warning |
| symlink 已存在且有效 | 跳过，打印 "already set up" |
