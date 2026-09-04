"""Tool and CLI module for incremental synchronization of ChainerTrader to forchain/ChainerTrader."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

TZ_SHANGHAI = timezone(timedelta(hours=8))
DEFAULT_TARGET_REPO = "forchain/ChainerTrader"
DEFAULT_REMOTE_NAME = "forchain"
DEFAULT_AUTHOR = "outlier <outlier@chainer.tech>"


@dataclass
class CommitInfo:
    hash: str
    timestamp: int
    date: datetime
    subject: str


@dataclass
class WeekGroup:
    week_num: int
    iso_week: str
    commits: list[CommitInfo]
    target_version: str
    branch_name: str
    pr_title: str
    pr_body: str = ""


@dataclass
class RemoteState:
    latest_week: int = 0
    latest_version: str | None = None
    latest_tag: str | None = None


@dataclass
class SyncPlan:
    is_up_to_date: bool
    latest_remote_state: RemoteState
    pending_weeks: list[WeekGroup] = field(default_factory=list)


def format_version(week_num: int, commit_count: int) -> str:
    """Format version as 0.aaa.bbb where aaa is week/PR ID, bbb is commit count."""
    return f"0.{week_num}.{commit_count}"


def generate_branch_slug(week_num: int, lead_subject: str) -> str:
    """Generate compliant branch name feat/w{aaa:02d}-{slug}."""
    cleaned = re.sub(
        r"^(feat|fix|refactor|test|docs|chore|bug)(\([^\)]+\))?:\s*",
        "",
        lead_subject,
        flags=re.I,
    )
    cleaned = re.sub(r"[^a-zA-Z0-9\s-]", "", cleaned).strip().lower()
    words = [w for w in cleaned.split() if len(w) > 1][:4]
    slug = "-".join(words) if words else "updates"
    return f"feat/w{week_num:02d}-{slug}"


def group_commits_by_iso_week(
    commits: list[CommitInfo], tz: timezone = TZ_SHANGHAI
) -> list[WeekGroup]:
    """Group commits into ISO calendar weeks in the specified timezone."""
    weeks_dict: dict[str, list[CommitInfo]] = {}
    for c in commits:
        dt = c.date if c.date.tzinfo else c.date.replace(tzinfo=timezone.utc).astimezone(tz)
        iso = dt.isocalendar()
        key = f"{iso[0]}-W{iso[1]:02d}"
        if key not in weeks_dict:
            weeks_dict[key] = []
        weeks_dict[key].append(c)

    result = []
    for key, c_list in weeks_dict.items():
        result.append(
            WeekGroup(
                week_num=0,
                iso_week=key,
                commits=c_list,
                target_version="",
                branch_name="",
                pr_title="",
            )
        )
    return result


def parse_latest_remote_state(release_list_text: str) -> RemoteState:
    """Parse output of gh release list to extract the highest week number and release tag."""
    if not release_list_text or not release_list_text.strip():
        return RemoteState(latest_week=0, latest_version=None, latest_tag=None)

    highest_week = 0
    highest_tag = None
    highest_version = None

    for line in release_list_text.strip().splitlines():
        # Look for pattern v0.<week>.<commits>
        match = re.search(r"v0\.(\d+)\.(\d+)", line)
        if match:
            w_num = int(match.group(1))
            v_str = f"0.{match.group(1)}.{match.group(2)}"
            tag = f"v{v_str}"
            if w_num > highest_week:
                highest_week = w_num
                highest_tag = tag
                highest_version = v_str

    return RemoteState(
        latest_week=highest_week,
        latest_version=highest_version,
        latest_tag=highest_tag,
    )


def build_pr_body(
    week_num: int, iso_week: str, commits: list[CommitInfo], version_str: str, lead_subject: str
) -> str:
    """Construct structured markdown PR body."""
    date_start = commits[0].date.strftime("%Y-%m-%d")
    date_end = commits[-1].date.strftime("%Y-%m-%d")
    commit_bullets = "\n".join(
        [
            f"- `{c.hash[:7]}` {c.subject} ({c.date.strftime('%Y-%m-%d')})"
            for c in commits[:15]
        ]
    )
    if len(commits) > 15:
        commit_bullets += f"\n- ... and {len(commits) - 15} more commits"

    return f"""## Summary
- **Week**: {week_num:02d} ({iso_week})
- **Period**: {date_start} to {date_end}
- **Commits**: {len(commits)}
- **Version**: `{version_str}`

### Overview
{lead_subject}

### Included Commits
{commit_bullets}
"""


def plan_open_sync(
    commits: list[CommitInfo], starting_week: int, tz: timezone = TZ_SHANGHAI
) -> SyncPlan:
    """Analyze pending commits and build synchronization plan."""
    if not commits:
        return SyncPlan(
            is_up_to_date=True,
            latest_remote_state=RemoteState(latest_week=starting_week),
            pending_weeks=[],
        )

    raw_weeks = group_commits_by_iso_week(commits, tz=tz)
    pending_weeks = []

    current_week = starting_week
    for rw in raw_weeks:
        current_week += 1
        v_str = format_version(current_week, len(rw.commits))

        valid_subjects = [
            c.subject for c in rw.commits if not c.subject.startswith("Merge ")
        ]
        lead_subject = valid_subjects[0] if valid_subjects else rw.commits[0].subject
        b_name = generate_branch_slug(current_week, lead_subject)
        pr_title = f"feat: week {current_week:02d} - {lead_subject[:70]}"
        pr_body = build_pr_body(current_week, rw.iso_week, rw.commits, v_str, lead_subject)

        pending_weeks.append(
            WeekGroup(
                week_num=current_week,
                iso_week=rw.iso_week,
                commits=rw.commits,
                target_version=v_str,
                branch_name=b_name,
                pr_title=pr_title,
                pr_body=pr_body,
            )
        )

    return SyncPlan(
        is_up_to_date=len(pending_weeks) == 0,
        latest_remote_state=RemoteState(latest_week=starting_week),
        pending_weeks=pending_weeks,
    )


plan_forchain_sync = plan_open_sync


class RealGitRunner:
    """Default real Git execution engine."""

    def __init__(self, repo_dir: str, env: dict[str, str] | None = None):
        self.repo_dir = repo_dir
        self.env = env or os.environ.copy()

    def run(self, cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd, cwd=self.repo_dir, env=self.env, check=check, capture_output=True, text=True
        )

    def checkout(self, branch: str, base: str | None = None) -> None:
        if base:
            self.run(["git", "checkout", "-B", branch, base])
        else:
            self.run(["git", "checkout", branch])

    def pull(self, remote: str, branch: str) -> None:
        self.run(["git", "pull", remote, branch])

    def push(self, remote: str, branch: str) -> None:
        self.run(["git", "push", remote, branch])

    def apply_commit(self, c: CommitInfo) -> None:
        c_env = self.env.copy()
        c_env["GIT_AUTHOR_NAME"] = "outlier"
        c_env["GIT_AUTHOR_EMAIL"] = "outlier@chainer.tech"
        c_env["GIT_COMMITTER_NAME"] = "outlier"
        c_env["GIT_COMMITTER_EMAIL"] = "outlier@chainer.tech"
        c_env["GIT_AUTHOR_DATE"] = f"{c.timestamp} +0800"
        c_env["GIT_COMMITTER_DATE"] = f"{c.timestamp} +0800"

        res = subprocess.run(
            ["git", "cherry-pick", "-Xtheirs", c.hash],
            cwd=self.repo_dir,
            env=c_env,
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            err = res.stderr
            if "empty" in err or "nothing to commit" in err:
                subprocess.run(["git", "cherry-pick", "--abort"], cwd=self.repo_dir, capture_output=True)
                subprocess.run(["git", "commit", "--allow-empty", "-m", c.subject], cwd=self.repo_dir, env=c_env, check=True)
            else:
                subprocess.run(["git", "checkout", "--theirs", "."], cwd=self.repo_dir, capture_output=True)
                subprocess.run(["git", "add", "-A"], cwd=self.repo_dir, check=True)
                status = subprocess.run(["git", "status", "--porcelain"], cwd=self.repo_dir, capture_output=True, text=True).stdout.strip()
                if status:
                    subprocess.run(["git", "commit", "-m", c.subject], cwd=self.repo_dir, env=c_env, check=True)
                else:
                    subprocess.run(["git", "commit", "--allow-empty", "-m", c.subject], cwd=self.repo_dir, env=c_env, check=True)
        else:
            subprocess.run(
                ["git", "commit", "--amend", "--author=outlier <outlier@chainer.tech>", "--no-edit"],
                cwd=self.repo_dir,
                env=c_env,
                check=True,
            )

    def bump_version(self, version_str: str, timestamp: int) -> None:
        c_env = self.env.copy()
        c_env["GIT_AUTHOR_NAME"] = "outlier"
        c_env["GIT_AUTHOR_EMAIL"] = "outlier@chainer.tech"
        c_env["GIT_COMMITTER_NAME"] = "outlier"
        c_env["GIT_COMMITTER_EMAIL"] = "outlier@chainer.tech"
        c_env["GIT_AUTHOR_DATE"] = f"{timestamp} +0800"
        c_env["GIT_COMMITTER_DATE"] = f"{timestamp} +0800"

        v_paths = [
            os.path.join(self.repo_dir, "src", "trader", "VERSION"),
            os.path.join(self.repo_dir, "trader", "VERSION"),
        ]
        for vp in v_paths:
            if os.path.exists(os.path.dirname(vp)):
                with open(vp, "w") as vf:
                    vf.write(f"{version_str}\n")
                break

        pyproject_path = os.path.join(self.repo_dir, "pyproject.toml")
        if os.path.exists(pyproject_path):
            with open(pyproject_path, "r") as pf:
                content = pf.read()
            new_content = re.sub(r'version\s*=\s*"[^"]+"', f'version = "{version_str}"', content, count=1)
            with open(pyproject_path, "w") as pf:
                pf.write(new_content)

        subprocess.run(["git", "add", "-A"], cwd=self.repo_dir, check=True)
        subprocess.run(
            ["git", "commit", "--amend", "--author=outlier <outlier@chainer.tech>", "--no-edit"],
            cwd=self.repo_dir,
            env=c_env,
            check=True,
        )


class RealGhRunner:
    """Default real GitHub CLI execution engine."""

    def __init__(self, env: dict[str, str] | None = None):
        self.env = env or os.environ.copy()

    def list_releases(self, repo: str) -> str:
        res = subprocess.run(
            ["gh", "release", "list", "--repo", repo, "--limit", "100"],
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout

    def create_pr(self, repo: str, base: str, head: str, title: str, body: str) -> str:
        res = subprocess.run(
            [
                "gh", "pr", "create",
                "--repo", repo,
                "--base", base,
                "--head", head,
                "--title", title,
                "--body", body,
            ],
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()

    def merge_pr(self, pr_number: int, repo: str) -> None:
        for attempt in range(6):
            time.sleep(2)
            res = subprocess.run(
                [
                    "gh", "pr", "merge", str(pr_number),
                    "--repo", repo,
                    "--merge",
                    "--delete-branch=false",
                ],
                env=self.env,
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                return
            time.sleep(3)
        raise RuntimeError(f"Failed to merge PR #{pr_number} on {repo}")

    def create_release(self, repo: str, tag: str, target: str, title: str, notes: str) -> str:
        res = subprocess.run(
            [
                "gh", "release", "create", tag,
                "--repo", repo,
                "--target", target,
                "--title", title,
                "--notes", notes,
            ],
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()


def execute_open_sync(
    plan: SyncPlan,
    repo_dir: str,
    target_repo: str = DEFAULT_TARGET_REPO,
    remote_name: str = DEFAULT_REMOTE_NAME,
    check_only: bool = False,
    dry_run: bool = False,
    git_runner: Any = None,
    gh_runner: Any = None,
) -> dict[str, Any]:
    """Execute the synchronization plan against the target repository."""
    if plan.is_up_to_date:
        return {
            "status": "up-to-date",
            "message": "Already up to date with forchain/ChainerTrader",
            "pending_count": 0,
            "migrated_weeks": [],
        }

    if check_only:
        return {
            "status": "checked",
            "pending_count": len(plan.pending_weeks),
            "pending_weeks": [
                {
                    "week_num": w.week_num,
                    "iso_week": w.iso_week,
                    "commits_count": len(w.commits),
                    "target_version": w.target_version,
                    "branch_name": w.branch_name,
                    "title": w.pr_title,
                }
                for w in plan.pending_weeks
            ],
        }

    git = git_runner or RealGitRunner(repo_dir=repo_dir)
    gh = gh_runner or RealGhRunner()

    migrated = []
    for w in plan.pending_weeks:
        # 1. Update main branch
        git.checkout("main")
        if not dry_run:
            git.pull(remote_name, "main")

        # 2. Branch out
        git.checkout(w.branch_name, base="main")

        # 3. Apply commits
        for c in w.commits:
            git.apply_commit(c)

        # 4. Bump version on last commit
        last_ts = w.commits[-1].timestamp
        git.bump_version(w.target_version, last_ts)

        if dry_run:
            migrated.append(w.week_num)
            continue

        # 5. Push branch
        git.push(remote=remote_name, branch=w.branch_name)

        # 6. Create PR
        gh.create_pr(
            repo=target_repo,
            base="main",
            head=w.branch_name,
            title=w.pr_title,
            body=w.pr_body,
        )

        # 7. Merge PR
        gh.merge_pr(pr_number=w.week_num, repo=target_repo)

        # 8. Pull main
        git.checkout("main")
        git.pull(remote_name, "main")

        # 9. Release
        tag_name = f"v{w.target_version}"
        release_title = f"{tag_name} - Week {w.week_num:02d}: {w.pr_title.replace(f'feat: week {w.week_num:02d} - ', '')}"
        gh.create_release(
            repo=target_repo,
            tag=tag_name,
            target="main",
            title=release_title,
            notes=w.pr_body,
        )

        migrated.append(w.week_num)
        time.sleep(2)

    return {
        "status": "success",
        "pending_count": len(plan.pending_weeks),
        "migrated_weeks": migrated,
    }


execute_forchain_sync = execute_open_sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Automated incremental synchronization of ChainerTrader to forchain/ChainerTrader"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check and display unmigrated commits/weeks without executing changes",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build local branch commits and version bumps without pushing to GitHub",
    )
    parser.add_argument(
        "--target-repo",
        default=DEFAULT_TARGET_REPO,
        help=f"Target GitHub repository (default: {DEFAULT_TARGET_REPO})",
    )
    parser.add_argument(
        "--remote-name",
        default=DEFAULT_REMOTE_NAME,
        help=f"Git remote name pointing to target repository (default: {DEFAULT_REMOTE_NAME})",
    )
    parser.add_argument(
        "--source-ref",
        default="HEAD",
        help="Local reference containing new commits to migrate (default: HEAD)",
    )

    args = parser.parse_args(argv)

    # Resolve token for forchain if available
    token = os.environ.get("GH_TOKEN")
    if not token:
        try:
            token = subprocess.check_output(
                ["gh", "auth", "token", "--user", "forchain"],
                text=True,
            ).strip()
        except Exception:
            pass

    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token

    gh_runner = RealGhRunner(env=env)

    # 1. Inspect remote state
    print(f"Querying latest state from {args.target_repo}...")
    try:
        release_text = gh_runner.list_releases(args.target_repo)
        remote_state = parse_latest_remote_state(release_text)
    except Exception as e:
        print(f"Error querying releases from {args.target_repo}: {e}", file=sys.stderr)
        return 1

    print(f"Latest remote release: {remote_state.latest_tag or 'None'} (Week {remote_state.latest_week})")

    # 2. Get local commits
    repo_dir = os.getcwd()
    cmd = ["git", "log", "--reverse", "--date-order", "--format=%H|%at|%s", args.source_ref]
    res = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error fetching commits from {args.source_ref}: {res.stderr}", file=sys.stderr)
        return 1

    lines = res.stdout.strip().splitlines()
    commits = []
    for line in lines:
        parts = line.split("|", 2)
        if len(parts) == 3:
            h, ts, s = parts[0], int(parts[1]), parts[2]
            commits.append(
                CommitInfo(
                    hash=h,
                    timestamp=ts,
                    date=datetime.fromtimestamp(ts, tz=TZ_SHANGHAI),
                    subject=s,
                )
            )

    # For incremental sync, we compare against total migrated weeks.
    # If 78 weeks are migrated, we check how many weeks currently exist in commits.
    all_weeks = group_commits_by_iso_week(commits, tz=TZ_SHANGHAI)
    print(f"Local total active weeks: {len(all_weeks)}")

    if len(all_weeks) <= remote_state.latest_week:
        print("✓ Already up to date! No unmigrated weeks detected.")
        return 0

    # New unmigrated weeks
    pending_raw_weeks = all_weeks[remote_state.latest_week:]
    pending_commits = []
    for pw in pending_raw_weeks:
        pending_commits.extend(pw.commits)

    plan = plan_open_sync(pending_commits, starting_week=remote_state.latest_week, tz=TZ_SHANGHAI)

    print(f"Found {len(plan.pending_weeks)} unmigrated week(s):")
    for pw in plan.pending_weeks:
        print(f"  - Week {pw.week_num:02d} ({pw.iso_week}): {len(pw.commits)} commit(s) -> Version {pw.target_version}, Branch: {pw.branch_name}")

    if args.check:
        print("\n[Check mode] No modifications made.")
        return 0

    # Execute
    git_runner = RealGitRunner(repo_dir=repo_dir, env=env)
    result = execute_open_sync(
        plan=plan,
        repo_dir=repo_dir,
        target_repo=args.target_repo,
        remote_name=args.remote_name,
        check_only=False,
        dry_run=args.dry_run,
        git_runner=git_runner,
        gh_runner=gh_runner,
    )

    print(f"\nMigration completed with status: {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
