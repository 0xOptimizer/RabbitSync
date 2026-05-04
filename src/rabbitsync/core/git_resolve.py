"""Resolve the git context of an arbitrary folder.

A registered RabbitSync folder may be:

1. **A git repo root** — the folder itself contains ``.git/``.
2. **A subfolder inside a git repo** — ``.git`` lives in some ancestor (e.g.
   the user's example: ``proj/src/`` is the registered folder, ``proj/.git``
   is the git directory).
3. **Not in any git repo at all** — RabbitSync still operates on the folder,
   git features are simply hidden for that side.

This module is the only place that classifies these cases. The result is an
immutable :class:`GitContext` consumed by every other module that needs to
know whether/where git applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rabbitsync.core.git import GitNotInstalledError, GitRunner


@dataclass(frozen=True)
class GitContext:
    """Where ``.git`` lives (if anywhere) for a registered folder.

    ``folder`` is the registered path (always set).
    ``git_root`` is the absolute path to the working-tree root that owns the
    folder, or ``None`` if no enclosing git repo was found.
    ``subpath`` is the folder's path relative to ``git_root``: empty string if
    folder *is* the root, ``None`` if there is no git context at all.
    ``git_dir`` is the resolved location of the ``.git`` directory itself,
    which may differ from ``git_root / ".git"`` for worktrees and ``.git``-as-
    file repositories. ``None`` when there is no git context.
    """

    folder: Path
    git_root: Path | None
    subpath: str | None
    git_dir: Path | None

    @property
    def has_git(self) -> bool:
        return self.git_root is not None

    @property
    def is_root(self) -> bool:
        """True if the registered folder *is* the git working-tree root."""
        return self.has_git and self.subpath == ""


def resolve(folder: Path, *, runner: GitRunner | None = None) -> GitContext:
    """Determine the git context of ``folder``.

    The lookup uses ``git rev-parse`` so it correctly handles worktrees,
    ``.git``-as-file repositories (submodules / linked worktrees), and case-
    insensitive Windows paths. If git is not installed the function falls
    back to a pure-Python ancestor walk for ``.git`` so basic folder
    registration still works (git features will surface a clear error later).
    """
    folder = folder.resolve(strict=False)
    if not folder.exists():
        raise FileNotFoundError(f"folder does not exist: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"not a directory: {folder}")

    try:
        return _resolve_via_git(folder, runner)
    except GitNotInstalledError:
        return _resolve_via_walk(folder)


def _resolve_via_git(folder: Path, runner: GitRunner | None) -> GitContext:
    r = runner if runner is not None else GitRunner()
    # `rev-parse --show-toplevel` prints the working-tree root, or fails
    # outside a repo. We use --no-optional-locks for safety on shared FS.
    result = r.run_at(
        folder,
        ["-c", "core.useBuiltinFSMonitor=false", "rev-parse", "--show-toplevel"],
        check=False,
    )
    if not result.ok:
        return GitContext(folder=folder, git_root=None, subpath=None, git_dir=None)
    root = Path(result.stdout.strip()).resolve(strict=False)

    git_dir_result = r.run_at(folder, ["rev-parse", "--git-dir"], check=False)
    if git_dir_result.ok:
        raw = git_dir_result.stdout.strip()
        candidate = Path(raw)
        git_dir = (folder / candidate).resolve(strict=False) if not candidate.is_absolute() else candidate
    else:
        git_dir = root / ".git"

    try:
        rel = folder.relative_to(root)
    except ValueError:
        # Should not happen if rev-parse said folder is inside the repo, but
        # be defensive about case-insensitive FS oddness.
        return GitContext(folder=folder, git_root=root, subpath="", git_dir=git_dir)
    subpath = "" if str(rel) == "." else rel.as_posix()
    return GitContext(folder=folder, git_root=root, subpath=subpath, git_dir=git_dir)


def _resolve_via_walk(folder: Path) -> GitContext:
    """Fallback when git binary is unavailable: walk ancestors looking for .git."""
    candidate = folder
    for ancestor in [candidate, *candidate.parents]:
        gd = ancestor / ".git"
        if gd.exists():
            try:
                rel = folder.relative_to(ancestor)
            except ValueError:
                rel = Path()
            subpath = "" if str(rel) in ("", ".") else rel.as_posix()
            return GitContext(folder=folder, git_root=ancestor, subpath=subpath, git_dir=gd)
    return GitContext(folder=folder, git_root=None, subpath=None, git_dir=None)


__all__ = ["GitContext", "resolve"]
