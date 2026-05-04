"""Read-only inspection of a git repository.

All accessors take a :class:`GitContext` so they short-circuit cleanly when
the registered folder isn't in a git repo. The :func:`status`,
:func:`branches`, :func:`remotes`, :func:`recent_commits`, and
:func:`ahead_behind` functions form the surface area used by the Git context
panes in the UI. Each parses a stable porcelain output of git so we don't
have to follow human-readable string changes across releases.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from rabbitsync.core.git import GitRunner
from rabbitsync.core.git_resolve import GitContext


@dataclass(frozen=True)
class WorkingTreeChange:
    """A single entry from ``git status --porcelain=v2``."""

    rel_path: str
    index_status: str   # "M", "A", "D", "R", "C", " " (unmodified in index), "?"
    worktree_status: str
    is_untracked: bool


@dataclass(frozen=True)
class WorkingTreeStatus:
    branch: str | None
    upstream: str | None
    ahead: int
    behind: int
    is_detached: bool
    changes: tuple[WorkingTreeChange, ...]

    @property
    def is_clean(self) -> bool:
        return not self.changes

    @property
    def modified_count(self) -> int:
        return sum(1 for c in self.changes if c.worktree_status == "M" or c.index_status == "M")

    @property
    def added_count(self) -> int:
        return sum(1 for c in self.changes if c.index_status == "A")

    @property
    def deleted_count(self) -> int:
        return sum(1 for c in self.changes if c.index_status == "D" or c.worktree_status == "D")

    @property
    def untracked_count(self) -> int:
        return sum(1 for c in self.changes if c.is_untracked)


@dataclass(frozen=True)
class Branch:
    name: str
    is_current: bool
    upstream: str | None
    last_commit_sha: str | None


@dataclass(frozen=True)
class Remote:
    name: str
    fetch_url: str | None
    push_url: str | None


@dataclass(frozen=True)
class Commit:
    sha: str
    short_sha: str
    parents: tuple[str, ...]
    author_name: str
    author_email: str
    author_time: int       # Unix seconds, UTC
    subject: str
    refs: tuple[str, ...]  # decorations: branch / tag names


def _runner_for(ctx: GitContext) -> GitRunner | None:
    if not ctx.has_git:
        return None
    assert ctx.git_root is not None
    return GitRunner(ctx.git_root)


def status(ctx: GitContext) -> WorkingTreeStatus | None:
    """Run ``git status --porcelain=v2 --branch`` and parse the output.

    Returns ``None`` when the folder has no git context.
    """
    r = _runner_for(ctx)
    if r is None:
        return None
    result = r.run(["status", "--porcelain=v2", "--branch", "--untracked-files=all"])
    return _parse_status(result.stdout)


def _parse_status(text: str) -> WorkingTreeStatus:
    branch: str | None = None
    upstream: str | None = None
    ahead = 0
    behind = 0
    is_detached = False
    changes: list[WorkingTreeChange] = []

    for raw_line in text.splitlines():
        if not raw_line:
            continue
        if raw_line.startswith("# "):
            # Header lines: "# branch.head <name>", "# branch.upstream <name>",
            # "# branch.ab +N -M", "# branch.oid <sha>".
            if raw_line.startswith("# branch.head "):
                head = raw_line[len("# branch.head ") :].strip()
                if head == "(detached)":
                    is_detached = True
                else:
                    branch = head
            elif raw_line.startswith("# branch.upstream "):
                upstream = raw_line[len("# branch.upstream ") :].strip() or None
            elif raw_line.startswith("# branch.ab "):
                tail = raw_line[len("# branch.ab ") :].strip()
                ahead, behind = _parse_ab(tail)
            continue
        change = _parse_change_line(raw_line)
        if change is not None:
            changes.append(change)

    return WorkingTreeStatus(
        branch=branch,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        is_detached=is_detached,
        changes=tuple(changes),
    )


def _parse_ab(text: str) -> tuple[int, int]:
    """Parse ``+N -M`` from ``branch.ab`` header."""
    ahead = 0
    behind = 0
    for token in text.split():
        if token.startswith("+"):
            try:
                ahead = int(token[1:])
            except ValueError:
                pass
        elif token.startswith("-"):
            try:
                behind = int(token[1:])
            except ValueError:
                pass
    return ahead, behind


def _parse_change_line(line: str) -> WorkingTreeChange | None:
    """Parse one porcelain v2 change record.

    Formats we care about:
      ``1 XY sub mH mI mW hH hI path``           (ordinary changed entry)
      ``2 XY sub mH mI mW hH hI X<score> path<sep>orig_path``  (renamed/copied)
      ``? path``                                  (untracked)
      ``! path``                                  (ignored)
      ``u XY sub m1 m2 m3 mW h1 h2 h3 path``     (unmerged)
    """
    kind = line[0]
    if kind == "?":
        return WorkingTreeChange(rel_path=line[2:], index_status=" ", worktree_status="?", is_untracked=True)
    if kind == "!":
        return None  # ignored entries are not surfaced
    if kind == "1":
        fields = line.split(" ", 8)
        if len(fields) < 9:
            return None
        xy = fields[1]
        path = fields[8]
        return WorkingTreeChange(
            rel_path=path,
            index_status=xy[0],
            worktree_status=xy[1],
            is_untracked=False,
        )
    if kind == "2":
        fields = line.split(" ", 9)
        if len(fields) < 10:
            return None
        xy = fields[1]
        # Path field is "new\torig"; we surface the new path.
        path_field = fields[9]
        new_path = path_field.split("\t", 1)[0]
        return WorkingTreeChange(
            rel_path=new_path,
            index_status=xy[0],
            worktree_status=xy[1],
            is_untracked=False,
        )
    if kind == "u":
        fields = line.split(" ", 10)
        if len(fields) < 11:
            return None
        xy = fields[1]
        return WorkingTreeChange(
            rel_path=fields[10],
            index_status=xy[0],
            worktree_status=xy[1],
            is_untracked=False,
        )
    return None


def branches(ctx: GitContext) -> tuple[Branch, ...]:
    """List local branches with current marker, upstream, and last-commit sha."""
    r = _runner_for(ctx)
    if r is None:
        return ()
    fmt = "%(HEAD)%00%(refname:short)%00%(upstream:short)%00%(objectname)"
    result = r.run(["for-each-ref", f"--format={fmt}", "refs/heads"])
    out: list[Branch] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        head, name, upstream, sha = line.split("\x00", 3)
        out.append(
            Branch(
                name=name,
                is_current=(head.strip() == "*"),
                upstream=upstream or None,
                last_commit_sha=sha or None,
            )
        )
    return tuple(out)


def remotes(ctx: GitContext) -> tuple[Remote, ...]:
    """List configured remotes with their fetch and push URLs."""
    r = _runner_for(ctx)
    if r is None:
        return ()
    result = r.run(["remote", "-v"])
    by_name: dict[str, dict[str, str]] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        # "<name>\t<url> (fetch|push)"
        try:
            name, rest = line.split("\t", 1)
            url, kind = rest.rsplit(" ", 1)
        except ValueError:
            continue
        kind = kind.strip("()")
        by_name.setdefault(name, {})[kind] = url
    return tuple(
        Remote(name=name, fetch_url=urls.get("fetch"), push_url=urls.get("push"))
        for name, urls in by_name.items()
    )


def recent_commits(ctx: GitContext, *, limit: int = 50) -> tuple[Commit, ...]:
    """Return the most recent commits reachable from HEAD.

    Used for compact summaries; the full graph view uses ``core.git_graph``
    in a later phase.
    """
    r = _runner_for(ctx)
    if r is None:
        return ()
    fmt = "%H%x00%h%x00%P%x00%an%x00%ae%x00%at%x00%s%x00%D"
    result = r.run(
        ["log", "--no-color", f"--max-count={limit}", f"--pretty=format:{fmt}"],
        check=False,
    )
    if not result.ok:
        # Empty repo (no HEAD yet) is fine — return no commits.
        return ()
    return tuple(_parse_commits(result.stdout))


def _parse_commits(text: str) -> Iterator[Commit]:
    for line in text.splitlines():
        if not line:
            continue
        parts = line.split("\x00")
        if len(parts) < 8:
            continue
        sha, short, parents_str, an, ae, at, subject, decoration = parts[:8]
        parents = tuple(p for p in parents_str.split() if p)
        refs = tuple(_parse_decoration(decoration))
        try:
            author_time = int(at)
        except ValueError:
            author_time = 0
        yield Commit(
            sha=sha,
            short_sha=short,
            parents=parents,
            author_name=an,
            author_email=ae,
            author_time=author_time,
            subject=subject,
            refs=refs,
        )


def _parse_decoration(decoration: str) -> Iterator[str]:
    """Parse ``%D`` output, e.g. ``" (HEAD -> main, origin/main, tag: v1)"``."""
    decoration = decoration.strip()
    if decoration.startswith("(") and decoration.endswith(")"):
        decoration = decoration[1:-1]
    for raw in decoration.split(","):
        token = raw.strip()
        if not token:
            continue
        if "->" in token:
            # "HEAD -> main": surface "HEAD" and "main" as separate decorations.
            head, _, target = token.partition("->")
            yield head.strip()
            yield target.strip()
        else:
            yield token


def ahead_behind(ctx: GitContext) -> tuple[int, int] | None:
    """Return (ahead, behind) of the current branch against its upstream.

    ``None`` when there is no git context, no current branch, or no upstream.
    """
    s = status(ctx)
    if s is None or s.upstream is None:
        return None
    return (s.ahead, s.behind)


def head_sha(ctx: GitContext) -> str | None:
    """Return the full SHA of HEAD, or ``None`` if HEAD is unborn / no git."""
    r = _runner_for(ctx)
    if r is None:
        return None
    result = r.run(["rev-parse", "HEAD"], check=False)
    if not result.ok:
        return None
    return result.stdout.strip() or None


__all__ = [
    "Branch",
    "Commit",
    "Remote",
    "WorkingTreeChange",
    "WorkingTreeStatus",
    "ahead_behind",
    "branches",
    "head_sha",
    "recent_commits",
    "remotes",
    "status",
]


# `Path` is referenced for return-type clarity in API docs.
_ = Path
