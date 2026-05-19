# User Manual Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a comprehensive user manual in `docs/user-manual.md` and integrate it into the MkDocs navigation to guide traders and admins through the new multi-user platform.

**Architecture:** Role-based documentation structure integrated into the existing MkDocs static site generator setup.

**Tech Stack:** Markdown, MkDocs.

---

### Task 1: Integrate into MkDocs Navigation

**Files:**
- Modify: `mkdocs.yml`

- [ ] **Step 1: Update navigation**

Add "用户手册" to the `nav` section.

```yaml
site_name: trader
theme: readthedocs
nav:
  - Home: index.md
  - 用户手册: user-manual.md
  - About: about.md
```

- [ ] **Step 2: Commit changes**

```bash
git add mkdocs.yml
git commit -m "docs: add user manual to mkdocs navigation"
```

---

### Task 2: Initialize User Manual and Write Introduction

**Files:**
- Create: `docs/user-manual.md`

- [ ] **Step 1: Create file with Introduction and Overview**

```markdown
# ChainerTrader 用户手册

欢迎使用 ChainerTrader 多用户管理后台。本平台支持账户隔离、策略管理、任务监控以及安全的 API 凭据存储。

## 核心概念

- **账户隔离**：每个用户拥有独立的策略配置、任务记录和交易所凭据。
- **凭据安全**：所有交易所 API Key/Secret 均使用服务器级密钥加密存储，确保即便数据库泄露，凭据依然安全。
- **角色体系**：分为 **交易员 (Trader)** 和 **管理员 (Admin)** 两种角色。

---
```

- [ ] **Step 2: Commit initial draft**

```bash
git add docs/user-manual.md
git commit -m "docs: initialize user manual with introduction"
```

---

### Task 3: Write Trader's Guide - Account and Credentials

**Files:**
- Modify: `docs/user-manual.md`

- [ ] **Step 1: Append Account and Credential sections**

```markdown
## 交易员指南 (Trader's Guide)

### 1. 账户管理

#### 注册与登录
- **注册**：访问 `/register` 页面，输入用户名（3-32位）和密码（至少10位，需包含字母和数字）。
- **登录**：访问 `/login` 页面进行身份验证。
- **修改密码**：登录后可在“我的账号”页面修改登录密码。

### 2. 交易所凭据管理 (Exchange Credentials)

在运行实盘任务前，您需要配置交易所 API 凭据：
1. 进入 **My Account -> Exchange Credentials** 页面。
2. 点击 **Add Credential**。
3. 选择交易所（如 `binance`），输入您的 API Key 和 API Secret。
4. **安全性说明**：您的凭据将被加密。如果服务器未配置 `TRADER_SECRET_KEY`，该功能将被禁用。
---
```

- [ ] **Step 2: Commit Trader's Guide updates**

```bash
git add docs/user-manual.md
git commit -m "docs: add account and credentials sections to user manual"
```

---

### Task 4: Write Trader's Guide - Strategy and Task Center

**Files:**
- Modify: `docs/user-manual.md`

- [ ] **Step 1: Append Strategy and Task sections**

```markdown
### 3. 策略管理 (Strategy Management)

- **创建配置**：在 **Strategy Management** 页面，您可以保存常用的策略参数（如 Symbol, Interval, Parameters）。
- **复用性**：保存后的配置可用于多次任务运行。

### 4. 任务中心 (Task Center)

任务中心是执行策略的核心：
- **启动任务**：
    - 选择一个保存的策略配置。
    - 选择任务类型：**Backtest (回测)** 或 **Live (实盘)**。
    - **实盘注意事项**：启动实盘任务时，系统会自动关联您名下的相应交易所凭据。
- **监控与日志**：
    - 在任务详情页可以查看实时运行日志。
    - 任务完成后可以查看回测报告或实盘统计。

---
```

- [ ] **Step 2: Commit Strategy and Task sections**

```bash
git add docs/user-manual.md
git commit -m "docs: add strategy and task center sections to user manual"
```

---

### Task 5: Write Administrator's Guide

**Files:**
- Modify: `docs/user-manual.md`

- [ ] **Step 1: Append Administrator sections**

```markdown
## 管理员指南 (Administrator's Guide)

管理员负责平台的日常维护和用户管理。

### 1. 引导第一个管理员 (Bootstrapping)

系统首次启动时，若数据库中没有管理员，系统会根据环境变量创建默认账号：
- `ADMIN_USER`: 默认管理员用户名。
- `ADMIN_PASSWORD`: 默认管理员密码。

### 2. 用户管理

管理员可以在 **Platform Management** 页面执行以下操作：
- **查看用户**：列出系统中所有已注册的用户及其状态。
- **重置密码**：如果用户忘记密码，管理员可以为其生成一个随机的临时密码。用户使用临时密码登录后将被强制要求修改密码。

### 3. 系统监控

- **平台任务概览**：查看全平台正在运行的任务数量和状态。
- **安全保障**：请确保服务器环境变量 `TRADER_SECRET_KEY` 已妥善备份，它是解密所有用户交易所凭据的唯一钥匙。
```

- [ ] **Step 2: Commit Administrator's Guide**

```bash
git add docs/user-manual.md
git commit -m "docs: add administrator guide section to user manual"
```

---

### Task 6: Final Validation and MkDocs Build

**Files:**
- N/A

- [ ] **Step 1: Verify file content and links**

检查 `docs/user-manual.md` 是否包含所有预期部分，且 Markdown 格式正确。

- [ ] **Step 2: (可选) 本地构建验证**

如果环境中安装了 `mkdocs`，可以尝试运行：
```bash
mkdocs build
```
验证是否有构建错误。
