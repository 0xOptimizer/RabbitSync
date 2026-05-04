"""Preflight checks — every state-changing operation calls into here first.

A failed preflight is a clear, actionable refusal to proceed: the message
names the cause and the fix.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from rabbitsync.core.git_resolve import GitContext


class PreflightError(RuntimeError):
    """Raised by preflight checks; the message is user-facing."""


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def for_sync(
    *,
    source_folder: Path,
    copy_folder: Path,
    copy_ctx: GitContext,
    expected_change_bytes: int = 0,
    require_clean_copy: bool = False,
) -> PreflightResult:
    """Run every preflight check appropriate for a sync.

    ``require_clean_copy`` is true on the second-and-later sync of a pair;
    initial-sync allows a dirty copy because the user explicitly opts in via
    the typed-confirm dialog.
    """
    blockers: list[str] = []
    warnings: list[str] = []

    if not source_folder.exists():
        blockers.append(
            f"Source folder does not exist: {source_folder}. "
            "Re-pick or remove the pair."
        )
    elif not source_folder.is_dir():
        blockers.append(f"Source path is not a directory: {source_folder}.")

    if not copy_folder.exists():
        blockers.append(
            f"Copy folder does not exist: {copy_folder}. "
            "Re-pick or remove the pair."
        )
    elif not copy_folder.is_dir():
        blockers.append(f"Copy path is not a directory: {copy_folder}.")

    if blockers:
        # Don't run the rest of the checks against missing folders.
        return PreflightResult(ok=False, blockers=tuple(blockers), warnings=tuple(warnings))

    # Check disk space (rough heuristic: 2x the expected change set).
    needed = max(expected_change_bytes * 2, 64 * 1024 * 1024)  # at least 64 MB headroom
    free = _free_bytes(copy_folder)
    if free is not None and free < needed:
        blockers.append(
            f"Insufficient free disk space on {copy_folder.anchor}: "
            f"have {_fmt_bytes(free)}, need ≥ {_fmt_bytes(needed)} for safe sync."
        )

    # Detached HEAD on copy is allowed for read but problematic for commit/push.
    # We surface as a warning here; the commit-on-sync flow will refuse if needed.
    if copy_ctx.has_git:
        # The actual detached-state check happens in git_info.status; here we
        # only verify the .git directory is reachable.
        if copy_ctx.git_dir is not None and not copy_ctx.git_dir.exists():
            blockers.append(
                f"Copy is registered as a git repo but its .git directory is missing "
                f"({copy_ctx.git_dir}). Reinitialize or remove the pair."
            )

    # Dirty copy gating (caller decides whether to enforce).
    if require_clean_copy:
        # The actual dirty/clean determination needs status(); the caller is
        # expected to check this separately and pass the appropriate flag.
        # Documented here so the contract is visible in one place.
        pass

    return PreflightResult(
        ok=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def _free_bytes(path: Path) -> int | None:
    try:
        return shutil.disk_usage(path).free
    except (FileNotFoundError, OSError):
        return None


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n //= 1024  # type: ignore[assignment]
    return f"{n} PB"


__all__ = ["PreflightError", "PreflightResult", "for_sync"]
