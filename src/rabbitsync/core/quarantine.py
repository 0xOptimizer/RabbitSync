"""Soft-delete: the ONLY path that may remove a file from a user repo.

Threat model
------------
Sync may need to remove orphan files from copy (files that existed last sync
but are no longer in source). A bug in the diff engine, a stale ignore file,
or an accidental deletion in source could otherwise cause irreversible loss
in copy. Quarantine guarantees recoverability until retention sweeps the
quarantine entry.

Hard rules enforced elsewhere
-----------------------------
A custom AST lint rule (added in CI) forbids ``os.remove``, ``os.unlink``,
``shutil.rmtree``, and ``Path.unlink`` in modules that touch user-repo
working trees. **This module is the single sanctioned exception** for the
move-to-quarantine path; the underlying ``os.replace`` is a *move*, not a
delete.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from rabbitsync.paths import quarantine_dir


@dataclass(frozen=True)
class QuarantineEntry:
    """A file that has been moved to quarantine."""

    sync_id: str
    rel_path: str
    quarantine_path: Path
    original_path: Path


def quarantine_root_for(sync_id: str) -> Path:
    """Return ``data/quarantine/<sync-id>/`` — created if missing."""
    p = quarantine_dir() / sync_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def move_to_quarantine(*, sync_id: str, file_path: Path, rel_path: str) -> QuarantineEntry:
    """Move a single file into the quarantine tree.

    The relative path inside quarantine mirrors the file's relative path
    inside copy, so a future restore can map back unambiguously.
    Idempotent: if the source no longer exists, we treat it as already
    quarantined (likely from an earlier crash) and surface a clean record.
    """
    target = quarantine_root_for(sync_id) / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)

    if not file_path.exists():
        # Already moved (or vanished out from under us); record what we know.
        return QuarantineEntry(
            sync_id=sync_id,
            rel_path=rel_path,
            quarantine_path=target,
            original_path=file_path,
        )

    # Use shutil.move so we cross filesystem boundaries cleanly if needed.
    # On Windows, Path.replace is atomic only on the same volume; shutil.move
    # falls back to copy+delete if not, but the source is RabbitSync's own
    # data tree which lives on the same drive as copy by construction.
    shutil.move(str(file_path), str(target))
    return QuarantineEntry(
        sync_id=sync_id,
        rel_path=rel_path,
        quarantine_path=target,
        original_path=file_path,
    )


def restore_one(entry: QuarantineEntry) -> Path:
    """Move a quarantined file back to its original path.

    The destination must not exist (we never overwrite a live file as part
    of recovery). Returns the destination path.
    """
    if entry.original_path.exists():
        raise FileExistsError(
            f"cannot restore over existing file: {entry.original_path}"
        )
    entry.original_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(entry.quarantine_path), str(entry.original_path))
    return entry.original_path


__all__ = ["QuarantineEntry", "move_to_quarantine", "quarantine_root_for", "restore_one"]
