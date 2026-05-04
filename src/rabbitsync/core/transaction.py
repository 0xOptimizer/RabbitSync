"""Atomic file-op transaction with journal-backed rollback.

Threat model
------------
A sync touches many files in copy. If the process crashes mid-write, leaves
must be cleanly rolled back so the user is never left with a half-applied
state.

Approach
--------
Every write is staged: ``<dest>.rabbitsync.tmp`` is written, fsynced, then
atomically renamed to ``<dest>``. Every "delete" is performed by quarantining
the original (see ``core.quarantine``). The journal records each staged step
*before* it runs, so on crash recovery we can:

- For incomplete write steps: delete any leftover ``.rabbitsync.tmp`` files.
- For completed write steps: leave them in place (the new file is already
  good) or restore the prior content from the snapshot if the user opts to
  rollback.
- For quarantine steps: nothing to undo automatically (the original file is
  in quarantine and recoverable on demand).

This Phase-3 module provides the **plan + apply contract**. The actual
write-and-fsync implementation runs from Phase 5 onward; here we define the
data classes the diff engine produces and the journal records.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path


class StepKind(enum.StrEnum):
    """The atomic operations a sync transaction performs."""

    WRITE = "write"           # write source content to copy/<rel>
    QUARANTINE = "quarantine" # move copy/<rel> into data/quarantine/<sync-id>/<rel>


@dataclass(frozen=True)
class TransactionStep:
    """One unit of work in a sync transaction.

    ``rel_path`` is relative to the copy folder. For ``WRITE`` steps the
    payload comes from ``source_abs_path``. For ``QUARANTINE`` steps the
    target file is ``copy_abs_path``.
    """

    kind: StepKind
    rel_path: str
    copy_abs_path: Path
    source_abs_path: Path | None  # only for WRITE
    expected_source_hash: str | None = None  # for WRITE: pre-write source hash
    expected_copy_hash: str | None = None    # for QUARANTINE: pre-quarantine hash

    def __post_init__(self) -> None:
        if self.kind == StepKind.WRITE and self.source_abs_path is None:
            raise ValueError("WRITE step requires source_abs_path")
        if self.kind == StepKind.QUARANTINE and self.source_abs_path is not None:
            raise ValueError("QUARANTINE step must not carry source_abs_path")


@dataclass(frozen=True)
class TransactionPlan:
    """Ordered list of steps that, when applied, converge copy to source.

    Steps are deterministically ordered: writes (sorted by rel_path) first,
    then quarantines. This matches the user-visible diff: adds + modifies
    happen, then orphan removals take effect.
    """

    sync_id: str
    steps: tuple[TransactionStep, ...] = field(default_factory=tuple)

    @property
    def write_count(self) -> int:
        return sum(1 for s in self.steps if s.kind == StepKind.WRITE)

    @property
    def quarantine_count(self) -> int:
        return sum(1 for s in self.steps if s.kind == StepKind.QUARANTINE)


def temp_path_for(dest: Path) -> Path:
    """Return the staging path used for atomic-rename writes."""
    return dest.with_name(dest.name + ".rabbitsync.tmp")


__all__ = [
    "StepKind",
    "TransactionPlan",
    "TransactionStep",
    "temp_path_for",
]
