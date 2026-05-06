"""Generate ``RabbitSync: …`` commit messages from sync diff plans / git status.

All RabbitSync-authored commits are prefixed with ``RabbitSync:`` so they're
trivially identifiable in copy's history. The body summarizes what changed.
"""

from __future__ import annotations

import re

from rabbitsync.core.diff import DiffPlan
from rabbitsync.core.git_info import WorkingTreeStatus

PREFIX = "RabbitSync"


def _split_path(rel_path: str) -> tuple[str, str]:
    rel = rel_path.replace("\\", "/")
    parts = rel.split("/", 1)
    if len(parts) == 1:
        return "", parts[0]
    return parts[0], parts[1]


def _summarize_paths(rel_paths: list[str], *, max_listed: int = 3) -> str:
    if not rel_paths:
        return ""
    if len(rel_paths) <= max_listed:
        return ", ".join(rel_paths)
    head = ", ".join(rel_paths[:max_listed])
    return f"{head}, +{len(rel_paths) - max_listed} more"


def _common_top_dir(rel_paths: list[str]) -> str | None:
    """Return the shared top-level directory, or None if there's no clear one."""
    tops = {_split_path(p)[0] for p in rel_paths}
    tops.discard("")
    if len(tops) == 1:
        only = next(iter(tops))
        return only or None
    return None


def for_sync(
    plan: DiffPlan,
    *,
    source_branch: str | None = None,
    source_sha: str | None = None,
) -> str:
    """Build the message body for a sync commit (no prefix)."""
    a = len(plan.adds)
    m = len(plan.modifies)
    q = len(plan.quarantines)
    n = a + m + q

    if n == 0:
        body = "no-op sync"
    elif n == 1:
        rel = (plan.adds + plan.modifies + plan.quarantines)[0].rel_path
        verb = "add" if a else ("update" if m else "remove")
        body = f"{verb} {rel}"
    else:
        all_rels = [c.rel_path for c in (*plan.adds, *plan.modifies, *plan.quarantines)]
        common = _common_top_dir(all_rels)
        scope = f" in {common}/" if common else ""
        parts: list[str] = []
        if a:
            parts.append(f"+{a} added")
        if m:
            parts.append(f"~{m} modified")
        if q:
            parts.append(f"-{q} removed")
        body = f"sync {n} files{scope} ({', '.join(parts)})"

    if source_branch and source_sha:
        body = f"{body} [src {source_branch}@{source_sha[:7]}]"
    elif source_sha:
        body = f"{body} [src@{source_sha[:7]}]"
    return body


def render(body: str) -> str:
    """Wrap ``body`` with the standard ``RabbitSync: …`` prefix."""
    body = body.strip()
    if not body:
        body = "(no message)"
    if body.startswith(f"{PREFIX}:"):
        return body
    return f"{PREFIX}: {body}"


def for_quick_push(status: WorkingTreeStatus | None) -> str:
    """Build the message body for a Quick Push (stage+commit+push) op.

    Uses the working-tree status: file counts and a few illustrative paths.
    """
    if status is None or not status.changes:
        return render("no changes")
    paths = [c.rel_path for c in status.changes]
    a = sum(1 for c in status.changes if c.index_status == "A" or c.is_untracked)
    m = sum(
        1 for c in status.changes
        if c.index_status == "M" or c.worktree_status == "M"
    )
    d = sum(
        1 for c in status.changes
        if c.index_status == "D" or c.worktree_status == "D"
    )
    n = len(status.changes)

    if n == 1:
        verb = "add" if a else ("remove" if d else "update")
        return render(f"{verb} {paths[0]}")

    common = _common_top_dir(paths)
    scope = f" in {common}/" if common else ""
    parts: list[str] = []
    if a:
        parts.append(f"+{a} added")
    if m:
        parts.append(f"~{m} modified")
    if d:
        parts.append(f"-{d} removed")
    listed = _summarize_paths(paths, max_listed=3)
    return render(f"update {n} files{scope} ({', '.join(parts)}); {listed}")


def is_safe_for_argv(message: str) -> bool:
    """True if the message has no NUL bytes or unprintable control chars."""
    return "\x00" not in message and not re.search(r"[\x01-\x08\x0b-\x1f]", message)


__all__ = ["PREFIX", "for_quick_push", "for_sync", "is_safe_for_argv", "render"]
