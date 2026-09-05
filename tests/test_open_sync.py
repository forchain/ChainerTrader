from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from trader.tools.open_sync import (
    CommitInfo,
    execute_open_sync,
    format_version,
    generate_branch_slug,
    group_commits_by_iso_week,
    parse_latest_remote_state,
    plan_open_sync,
)

TZ_SHANGHAI = timezone(timedelta(hours=8))


def test_format_version():
    assert format_version(1, 2) == "0.1.2"
    assert format_version(78, 2) == "0.78.2"
    assert format_version(79, 14) == "0.79.14"


def test_generate_branch_slug():
    # Regular feature message
    assert generate_branch_slug(1, "feat: support shihun macd") == "feat/w01-support-shihun-macd"
    # Fix with scope
    assert generate_branch_slug(77, "fix(auth): invalidate sessions after admin reset") == "feat/w77-invalidate-sessions-after-admin"
    # Fallback when subject is empty or special characters
    assert generate_branch_slug(2, "!!!") == "feat/w02-updates"


def test_group_commits_by_iso_week():
    # 2024-09-18 (Wed) and 2024-09-22 (Sun) -> same week 2024-W38
    dt1 = datetime(2024, 9, 18, 18, 55, tzinfo=TZ_SHANGHAI)
    dt2 = datetime(2024, 9, 22, 22, 48, tzinfo=TZ_SHANGHAI)
    # 2024-09-23 (Mon) -> next week 2024-W39
    dt3 = datetime(2024, 9, 23, 7, 42, tzinfo=TZ_SHANGHAI)

    c1 = CommitInfo(hash="hash1", timestamp=int(dt1.timestamp()), date=dt1, subject="commit 1")
    c2 = CommitInfo(hash="hash2", timestamp=int(dt2.timestamp()), date=dt2, subject="commit 2")
    c3 = CommitInfo(hash="hash3", timestamp=int(dt3.timestamp()), date=dt3, subject="commit 3")

    weeks = group_commits_by_iso_week([c1, c2, c3], tz=TZ_SHANGHAI)
    assert len(weeks) == 2
    assert weeks[0].iso_week == "2024-W38"
    assert len(weeks[0].commits) == 2
    assert weeks[1].iso_week == "2024-W39"
    assert len(weeks[1].commits) == 1


def test_parse_latest_remote_state():
    mock_releases = """
v0.78.2 - Week 78: feat: add user registration toggle\tLatest\tv0.78.2\t2026-09-04T11:21:33Z
v0.77.10 - Week 77: fix: invalidate sessions\t\tv0.77.10\t2026-09-04T11:21:11Z
"""
    state = parse_latest_remote_state(mock_releases)
    assert state.latest_week == 78
    assert state.latest_version == "0.78.2"
    assert state.latest_tag == "v0.78.2"


def test_parse_latest_remote_state_empty():
    state = parse_latest_remote_state("")
    assert state.latest_week == 0
    assert state.latest_version is None
    assert state.latest_tag is None


def test_plan_open_sync_up_to_date():
    commits = []  # No new commits since baseline
    plan = plan_open_sync(commits, starting_week=78, tz=TZ_SHANGHAI)
    assert plan.is_up_to_date is True
    assert len(plan.pending_weeks) == 0


def test_plan_open_sync_with_new_commits():
    dt1 = datetime(2026, 7, 27, 10, 0, tzinfo=TZ_SHANGHAI)  # Week 31
    dt2 = datetime(2026, 7, 28, 11, 0, tzinfo=TZ_SHANGHAI)
    dt3 = datetime(2026, 8, 3, 10, 0, tzinfo=TZ_SHANGHAI)  # Week 32

    c1 = CommitInfo(hash="h1", timestamp=int(dt1.timestamp()), date=dt1, subject="feat: new module")
    c2 = CommitInfo(hash="h2", timestamp=int(dt2.timestamp()), date=dt2, subject="fix: minor bug")
    c3 = CommitInfo(hash="h3", timestamp=int(dt3.timestamp()), date=dt3, subject="feat: next feature")

    plan = plan_open_sync([c1, c2, c3], starting_week=78, tz=TZ_SHANGHAI)
    assert plan.is_up_to_date is False
    assert len(plan.pending_weeks) == 2

    w79 = plan.pending_weeks[0]
    assert w79.week_num == 79
    assert len(w79.commits) == 2
    assert w79.target_version == "0.79.2"
    assert w79.branch_name == "feat/w79-new-module"

    w80 = plan.pending_weeks[1]
    assert w80.week_num == 80
    assert len(w80.commits) == 1
    assert w80.target_version == "0.80.1"
    assert w80.branch_name == "feat/w80-next-feature"


def test_execute_open_sync_check_only():
    mock_git = MagicMock()
    mock_gh = MagicMock()

    dt = datetime(2026, 7, 27, 10, 0, tzinfo=TZ_SHANGHAI)
    c1 = CommitInfo(hash="h1", timestamp=int(dt.timestamp()), date=dt, subject="feat: check test")
    plan = plan_open_sync([c1], starting_week=78, tz=TZ_SHANGHAI)

    result = execute_open_sync(
        plan=plan,
        repo_dir="/fake/repo",
        target_repo="forchain/ChainerTrader",
        remote_name="forchain",
        check_only=True,
        git_runner=mock_git,
        gh_runner=mock_gh,
    )

    assert result["status"] == "checked"
    assert result["pending_count"] == 1
    # No mutating operations called
    mock_git.push.assert_not_called()
    mock_gh.create_pr.assert_not_called()
    mock_gh.merge_pr.assert_not_called()
    mock_gh.create_release.assert_not_called()


def test_execute_open_sync_full_run():
    mock_git = MagicMock()
    mock_gh = MagicMock()

    dt = datetime(2026, 7, 27, 10, 0, tzinfo=TZ_SHANGHAI)
    c1 = CommitInfo(hash="h1", timestamp=int(dt.timestamp()), date=dt, subject="feat: execute test")
    plan = plan_open_sync([c1], starting_week=78, tz=TZ_SHANGHAI)

    result = execute_open_sync(
        plan=plan,
        repo_dir="/fake/repo",
        target_repo="forchain/ChainerTrader",
        remote_name="forchain",
        check_only=False,
        dry_run=False,
        git_runner=mock_git,
        gh_runner=mock_gh,
    )

    assert result["status"] == "success"
    assert result["migrated_weeks"] == [79]
    mock_git.push.assert_called_once_with(remote="forchain", branch="feat/w79-execute-test")
    mock_gh.create_pr.assert_called_once()
    mock_gh.merge_pr.assert_called_once_with(pr_number=79, repo="forchain/ChainerTrader")
    mock_gh.create_release.assert_called_once()
