"""Integration tests for ``core.git_info`` against real temp git repos."""

from __future__ import annotations

import subprocess
from pathlib import Path

from rabbitsync.core.git_info import (
    ahead_behind,
    branches,
    head_sha,
    recent_commits,
    remotes,
    status,
)
from rabbitsync.core.git_resolve import resolve


def _g(cwd: Path, *args: str) -> None:
    """Lightweight in-test git invocation; conftest's _git is private to it."""
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_AUTHOR_DATE": "2026-01-02T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-01-02T00:00:00Z",
        "GIT_CONFIG_GLOBAL": str(cwd / ".git_global_config"),
        "GIT_CONFIG_SYSTEM": str(cwd / ".git_system_config"),
        "PATH": __import__("os").environ.get("PATH", ""),
    }
    subprocess.run(  # noqa: S603, S607
        ["git", *args], cwd=str(cwd), env=env, capture_output=True, text=True, check=True
    )


def test_status_clean_repo(make_repo) -> None:  # noqa: ANN001
    repo = make_repo()
    s = status(resolve(repo))
    assert s is not None
    assert s.branch == "main"
    assert s.is_clean is True
    assert s.is_detached is False
    assert s.changes == ()


def test_status_modified_added_untracked(make_repo) -> None:  # noqa: ANN001
    repo = make_repo()
    # Modify an existing tracked file.
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    # Add a new file and stage it.
    (repo / "new.py").write_text("print('hi')\n", encoding="utf-8")
    _g(repo, "add", "new.py")
    # Add an untracked file.
    (repo / "ignored.tmp").write_text("temp\n", encoding="utf-8")

    s = status(resolve(repo))
    assert s is not None
    paths = {c.rel_path: c for c in s.changes}
    assert "README.md" in paths
    assert "new.py" in paths
    assert "ignored.tmp" in paths
    assert paths["ignored.tmp"].is_untracked is True
    assert paths["new.py"].index_status == "A"
    assert s.untracked_count == 1
    assert s.added_count == 1


def test_branches_lists_local_with_current_marker(make_repo) -> None:  # noqa: ANN001
    repo = make_repo()
    _g(repo, "branch", "feature-x")
    bs = branches(resolve(repo))
    names = {b.name: b for b in bs}
    assert "main" in names
    assert "feature-x" in names
    assert names["main"].is_current is True
    assert names["feature-x"].is_current is False
    assert names["main"].last_commit_sha is not None
    assert len(names["main"].last_commit_sha) == 40


def test_remotes_parses_fetch_and_push(make_repo) -> None:  # noqa: ANN001
    repo = make_repo()
    _g(repo, "remote", "add", "origin", "https://example.com/foo.git")
    rs = remotes(resolve(repo))
    by_name = {r.name: r for r in rs}
    assert "origin" in by_name
    assert by_name["origin"].fetch_url == "https://example.com/foo.git"
    assert by_name["origin"].push_url == "https://example.com/foo.git"


def test_recent_commits_returns_in_topological_order(make_repo, commit_file) -> None:  # noqa: ANN001
    repo = make_repo()
    commit_file(repo, "a.txt", "one\n", "add a")
    commit_file(repo, "b.txt", "two\n", "add b")
    commit_file(repo, "c.txt", "three\n", "add c")
    cs = recent_commits(resolve(repo), limit=10)
    subjects = [c.subject for c in cs]
    # Most recent first; the initial 'init' commit is the last entry.
    assert subjects[0] == "add c"
    assert subjects[1] == "add b"
    assert subjects[2] == "add a"
    assert subjects[3] == "init"
    # Parents recorded for non-root commits.
    assert cs[0].parents and len(cs[0].parents[0]) == 40
    # Init commit has no parents.
    assert cs[-1].parents == ()


def test_recent_commits_decoration_includes_head_branch(make_repo) -> None:  # noqa: ANN001
    repo = make_repo()
    cs = recent_commits(resolve(repo), limit=1)
    assert cs
    refs = set(cs[0].refs)
    assert "HEAD" in refs
    assert "main" in refs


def test_ahead_behind_against_upstream(make_repo, tmp_path: Path, commit_file) -> None:  # noqa: ANN001
    """Set up a bare upstream, clone it, make divergent local commits, check counts."""
    upstream = tmp_path / "upstream.git"
    upstream.mkdir()
    _g(upstream, "init", "--bare", "--initial-branch=main")

    work = make_repo("work")
    _g(work, "remote", "add", "origin", str(upstream))
    _g(work, "push", "-u", "origin", "main")

    # Commit two new local commits without pushing.
    commit_file(work, "x.txt", "1\n", "x1")
    commit_file(work, "y.txt", "2\n", "y2")

    ab = ahead_behind(resolve(work))
    assert ab == (2, 0)


def test_head_sha_returns_full_sha(make_repo) -> None:  # noqa: ANN001
    repo = make_repo()
    sha = head_sha(resolve(repo))
    assert sha is not None
    assert len(sha) == 40


def test_status_subpath_repo_reports_full_repo_state(make_subpath_repo, commit_file) -> None:  # noqa: ANN001
    """When the registered folder is a subpath, status reflects the *whole* repo
    (git itself doesn't restrict status to a subdirectory unless asked).
    """
    repo, sub = make_subpath_repo("proj", "src")
    # Modify a file outside the registered subpath.
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    s = status(resolve(sub))
    assert s is not None
    assert any(c.rel_path == "README.md" for c in s.changes)


def test_non_git_folder_returns_none_or_empty(make_non_git_dir) -> None:  # noqa: ANN001
    plain = make_non_git_dir()
    ctx = resolve(plain)
    assert status(ctx) is None
    assert branches(ctx) == ()
    assert remotes(ctx) == ()
    assert recent_commits(ctx) == ()
    assert ahead_behind(ctx) is None
    assert head_sha(ctx) is None
