# Black-Box Acceptance Orchestrator Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a reusable Codex skill that coordinates a project manager, development agent, and black-box testing agent, with real sub-agent support when available and explicit degraded-mode handling when it is not.

**Architecture:** Build a new skill directory with a concise `SKILL.md` for the workflow, an `agents/openai.yaml` for UI metadata, and a small `references/` file for the role/election rules that are likely to evolve. Keep project-specific knowledge out of the skill so the same skill can be reused in other repositories.

**Tech Stack:** Markdown skill content, optional YAML metadata, Codex skill initialization scripts, git.

---

### Task 1: Scaffold the new skill directory

**Files:**
- Create: `~/.codex/skills/blackbox-acceptance-orchestrator/SKILL.md`
- Create: `~/.codex/skills/blackbox-acceptance-orchestrator/agents/openai.yaml`
- Create: `~/.codex/skills/blackbox-acceptance-orchestrator/references/project-manager-rules.md`
- Create: `~/.codex/skills/blackbox-acceptance-orchestrator/assets/` only if an icon is added later

- [ ] **Step 1: Initialize the skill skeleton**

Run:
```bash
python /Users/tonyoutlier/.codex/skills/.system/skill-creator/scripts/init_skill.py blackbox-acceptance-orchestrator --path /Users/tonyoutlier/.codex/skills --resources references
```
Expected: a new skill directory exists with placeholder `SKILL.md` and `agents/openai.yaml`.

- [ ] **Step 2: Replace the scaffold with the actual workflow structure**

Write a workflow-based skill shell that names the four roles, explains the two execution modes, and points readers to the reference file for detailed escalation rules.

- [ ] **Step 3: Add the skill metadata**

Populate `agents/openai.yaml` with a clear display name, short description, and a default prompt that references `$blackbox-acceptance-orchestrator`.

- [ ] **Step 4: Add the role reference**

Write `references/project-manager-rules.md` with the role boundaries, escalation cases, black-box-only testing rule, and low-risk resource request pattern.

- [ ] **Step 5: Sanity-check the scaffold**

Run:
```bash
find /Users/tonyoutlier/.codex/skills/blackbox-acceptance-orchestrator -maxdepth 3 -type f | sort
```
Expected: `SKILL.md`, `agents/openai.yaml`, and `references/project-manager-rules.md` are present.

### Task 2: Write the skill behavior in `SKILL.md`

**Files:**
- Modify: `/Users/tonyoutlier/.codex/skills/blackbox-acceptance-orchestrator/SKILL.md`

- [ ] **Step 1: Rewrite the placeholder body into the real workflow**

Include these sections:
```markdown
# Black-Box Acceptance Orchestrator

## When to Use
- New development with a prompt or inferred task.
- Existing implementation acceptance from context.

## Roles
- User
- Project Manager
- Development Agent
- Testing Agent

## Workflow
- Detect whether the host supports real sub-agents.
- If supported, create separate development and testing agents.
- If unsupported, enter explicit degraded mode.
- Keep the testing agent black-box only.
- After user acceptance, record reusable lessons separately from project-specific assets.
```

- [ ] **Step 2: Keep the body lean**

Do not duplicate the detailed escalation rules in full; link to `references/project-manager-rules.md` instead.

- [ ] **Step 3: Make the restart/acceptance loop explicit**

Add the loop that returns to planning when the user finds a defect after the team has finished.

### Task 3: Add the UI metadata in `agents/openai.yaml`

**Files:**
- Modify: `/Users/tonyoutlier/.codex/skills/blackbox-acceptance-orchestrator/agents/openai.yaml`

- [ ] **Step 1: Write a stable human-facing label**

Use a short title like `Black-Box Acceptance Orchestrator`.

- [ ] **Step 2: Write the short description**

Keep it under the scan-friendly length and make it clear that the skill coordinates dev/test with black-box verification.

- [ ] **Step 3: Add the default prompt**

Use a one-sentence prompt that explicitly mentions `$blackbox-acceptance-orchestrator` and hints at the two supported modes.

- [ ] **Step 4: Validate the YAML shape**

Run:
```bash
python /Users/tonyoutlier/.codex/skills/.system/skill-creator/scripts/quick_validate.py /Users/tonyoutlier/.codex/skills/blackbox-acceptance-orchestrator
```
Expected: no metadata or structural validation errors.

### Task 4: Encode the project-manager rules in the reference file

**Files:**
- Modify: `/Users/tonyoutlier/.codex/skills/blackbox-acceptance-orchestrator/references/project-manager-rules.md`

- [ ] **Step 1: Write the escalation matrix**

Include the four escalation cases:
```markdown
- Requirements are ambiguous and cannot be inferred from context.
- Required resources are missing and cannot be satisfied through low-risk configuration.
- Project-specific constraints or domain knowledge are missing.
- Final acceptance still has unresolved disagreement after internal retries.
```

- [ ] **Step 2: Write the internal-resolution cases**

Include the cases that should stay inside the team:
```markdown
- Task splitting is needed.
- Developer and tester need another round.
- Testability improvements can be requested without user input.
- Missing information can be inferred from visible context or existing docs.
```

- [ ] **Step 3: Add the low-risk resource request pattern**

Document the preferred order:
1. `.env` or repository-managed config
2. Existing secret/config path
3. Dedicated test endpoint or admin command
4. Only then ask the user for confirmation of what cannot be represented safely

### Task 5: Add local validation and package checks

**Files:**
- Modify: `/Users/tonyoutlier/.codex/skills/blackbox-acceptance-orchestrator/*`

- [ ] **Step 1: Re-run the skill validator after the edits**

Run:
```bash
python /Users/tonyoutlier/.codex/skills/.system/skill-creator/scripts/quick_validate.py /Users/tonyoutlier/.codex/skills/blackbox-acceptance-orchestrator
```
Expected: validation succeeds.

- [ ] **Step 2: Manually inspect the skill for placeholders**

Check for `TODO`, `TBD`, and vague instructions. Replace any remaining placeholder text before moving on.

- [ ] **Step 3: Commit the skill**

Run:
```bash
git add /Users/tonyoutlier/.codex/skills/blackbox-acceptance-orchestrator
git commit -m "feat: add black-box acceptance orchestrator skill"
```
Expected: a single commit capturing the new reusable skill.

## Verification Checklist
- Skill directory exists under the user-level Codex skills path.
- `SKILL.md` describes the workflow without embedding project-specific details.
- `agents/openai.yaml` is populated and valid.
- The reference file captures the project-manager escalation rules.
- Validation passes with no placeholders or malformed metadata.

## Notes for Implementation
- Keep the skill generic enough to reuse in other repositories.
- Keep the project-manager rules explicit enough that the model can act without guessing.
- Do not add a README or extra docs inside the skill folder unless a future failure shows they are needed.
