"""Shared pytest fixtures.

Most fixtures here build temporary git repositories in isolated directories so
each test starts from a known state. Real ``git`` is invoked (no mocks) so
the integration tests exercise the same code paths the running app uses.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from rabbitsync.core.git import GitNotInstalledError, GitRunner


@pytest.fixture(scope="session")
def git_binary() -> str:
    """Skip the whole session early if git isn't installed."""
    try:
        return GitRunner.find_binary()
    except GitNotInstalledError as exc:
        pytest.skip(str(exc))


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in ``cwd`` with deterministic identity + branch.

    Uses environment variables to set the author/committer name+email and the
    initial branch, so tests don't depend on the host's global git config.
    """
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
        # Avoid the user's git config interfering.
        "GIT_CONFIG_GLOBAL": str(cwd / ".git_global_config"),
        "GIT_CONFIG_SYSTEM": str(cwd / ".git_system_config"),
        # Force initial branch to 'main' regardless of host default.
        "GIT_DEFAULT_BRANCH": "main",
    }
    return subprocess.run(  # noqa: S603, S607 -- argv list, git on PATH
        ["git", *args],
        cwd=str(cwd),
        env={**env, "PATH": __import__("os").environ.get("PATH", "")},
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture
def make_repo(tmp_path: Path, git_binary: str):  # noqa: ANN201 -- pytest fixture
    """Factory: create a fresh git repo at ``tmp_path / name`` with one commit.

    Returns the repo's working-tree root path.
    """

    def _make(name: str = "repo") -> Path:
        repo = tmp_path / name
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "-c", "init.defaultBranch=main", "init")
        # Force branch name to 'main' even on git<2.28
        _git(repo, "checkout", "-B", "main")
        (repo / "README.md").write_text("hello\n", encoding="utf-8")
        _git(repo, "add", "README.md")
        _git(repo, "commit", "-m", "init")
        return repo

    _ = git_binary
    return _make


@pytest.fixture
def make_subpath_repo(tmp_path: Path, git_binary: str):  # noqa: ANN201 -- pytest fixture
    """Factory: create a repo where the registered folder is a *subfolder*.

    Layout::

        proj/
          .git/
          src/        <-- the registered folder (subpath case)
            file.txt
    """

    def _make(name: str = "proj", sub: str = "src") -> tuple[Path, Path]:
        repo = tmp_path / name
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "-c", "init.defaultBranch=main", "init")
        _git(repo, "checkout", "-B", "main")
        (repo / "README.md").write_text("hello\n", encoding="utf-8")
        sub_dir = repo / sub
        sub_dir.mkdir(parents=True, exist_ok=True)
        (sub_dir / "file.txt").write_text("content\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "init")
        return repo, sub_dir

    _ = git_binary
    return _make


@pytest.fixture
def make_non_git_dir(tmp_path: Path):  # noqa: ANN201 -- pytest fixture
    """Factory: create a plain directory with no enclosing git repo."""

    def _make(name: str = "plain") -> Path:
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "note.txt").write_text("not a repo\n", encoding="utf-8")
        return d

    return _make


@pytest.fixture
def commit_file():  # noqa: ANN201 -- pytest fixture
    """Helper: write a file at ``repo/rel_path`` and commit it."""

    def _do(repo: Path, rel_path: str, content: str, message: str) -> None:
        target = repo / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        _git(repo, "add", rel_path)
        _git(repo, "commit", "-m", message)

    return _do


# Provide a helper for cleanup-needing tests
def _rmtree(p: Path) -> None:
    shutil.rmtree(p, ignore_errors=True)


_ = _rmtree  # exported via __all__ if needed in future
