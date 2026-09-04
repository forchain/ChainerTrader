---
name: daily-standup
description: 每日复盘技能 — 用于结束工作会话时生成结构化的日报，通过捕获精确的下一步动作（Next Steps）确保下一个 Agent 或会话能无缝衔接，实现“零启动时间”重启工作载入。
---

# 每日工作总结 (Daily Standup)

## 概述

生成一份结构化的工作日报，捕获当前会话的上下文、技术决策和未完成的任务。

**核心原则：任何没有参与过本次会话的人（包括未来的你或另一个 AI），在阅读此报告后，都应能立即通过报告中的“下一步”指令直接开展工作。**

## 报告模板

技能将基于 [template.md](file:///Users/tonyoutlier/github.com/ChainerLabs/ChainerTrader/.agent/skills/daily-standup/resources/template.md) 生成内容。

### 核心章节要求：
1. **概要 (Summary)**: 2-3句话总结今日最核心的变动。
2. **下一步 (Next Steps)**: 这是最关键的部分。禁止写模糊的“继续...”，必须包含：
   - **做什么**: 具体的原子化动作。
   - **在哪里**: `文件路径:行号` 或 `函数名`。
   - **上下文**: 为什么要这么做，解决什么痛点。
   - **怎么做**: 精确的 `CommandLine` 指令或代码逻辑描述。

## 执行流程

### 1. 自动收集上下文 (Parallel Execution)

在编写报告前，**必须**运行以下指令以确保数据准确：
- `git log -n 10 --oneline` (最近提交)
- `git diff --stat HEAD` (当前未提交变动)
- `git status` (当前分支状态)
- 检查 `tmp/` 或 `reports/` 目录下的最新产物（例如回测优化任务的状态）。

### 2. 生成报告

根据收集到的上下文，按照模板填写各章节。必须使用 **中文** 进行编写，但技术术语（如函数名、类、文件名）保持原样。

### 3. 持久化存储

报告必须保存至 `~/.antigravity/daily-standups/` 目录下。

**保存规则：**
- 文件路径：`~/.antigravity/daily-standups/YYYY-MM-DD.md`
- 命名冲突：如果当天已有报告，则使用 `YYYY-MM-DD-1.md` 累加序号。
- 写入前确保目录存在：`mkdir -p ~/.antigravity/daily-standups`

## 质量要求 (Guardrails)

- **原子化任务**：每个 Next Steps 条目必须是可直接由 `run_command` 执行或通过 `replace_file_content` 实施的明确指令。
- **排除干扰**：不要包含本次会话中已放弃的方案说明，只保留当前确定的路径和遗留问题。
- **环境隔离**：如果工作在 Git Worktree 中，请在“技术参考”中注明，以便下一个 Agent 初始化环境。
