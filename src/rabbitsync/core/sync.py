"""Sync orchestrator.

Glues every safety subsystem together to converge ``copy`` to ``source``:

1. Preflight (paths exist, disk space, git context healthy).
2. Snapshot copy folder (compressed, recorded in ``blobs``).
3. Compute diff (size+mtime fast path, hash on suspects, integrity sample).
4. Build a :class:`TransactionPlan` from the diff.
5. Open a sync row + journal; record each step before it runs.
6. Apply each step inside an atomic write/quarantine envelope.
7. Verify-after-sync: re-hash the changed files and assert convergence.
8. Append a hash-chained receipt and finalize the sync row.

A failure at any point aborts cleanly — the snapshot remains, the journal
is closed with status ``aborted`` or ``failed``, and the user can recover
from the snapshot with one click.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from rabbitsync.core.backup import Snapshot, take as snapshot_take
from rabbitsync.core.diff import DiffPlan, diff
from rabbitsync.core.git_resolve import resolve as resolve_git
from rabbitsync.core.hashing import sha256_file, xxh64_file
from rabbitsync.core.ignore import IgnoreRules, load_for_pair
from rabbitsync.core.quarantine import move_to_quarantine
from rabbitsync.core.transaction import (
    StepKind,
    TransactionPlan,
    TransactionStep,
    temp_path_for,
)
from rabbitsync.db.repositories import blobs_repo, receipts_repo, syncs_repo
from rabbitsync.db.writer import DbWriter
from rabbitsync.logging.setup import get_logger
from rabbitsync.safety import journal as journal_mod
from rabbitsync.safety.preflight import PreflightError, for_sync as preflight_for_sync

_log = get_logger("core.sync")


@dataclass(frozen=True)
class SyncOutcome:
    sync_id: str
    status: str  # 'ok' | 'aborted' | 'failed'
    snapshot: Snapshot | None
    diff_plan: DiffPlan
    files_added: int
    files_modified: int
    files_quarantined: int


def perform(
    *,
    pair_id: str,
    source_folder: Path,
    copy_folder: Path,
    writer: DbWriter,
    extra_ignore_files: tuple[Path, ...] = (),
    sample_rate: float = 0.01,
) -> SyncOutcome:
    """Run a full sync from source to copy. Returns the outcome.

    Raises :class:`PreflightError` if preflight refuses the run; otherwise
    every internal failure is caught and the sync is marked aborted/failed.
    """
    _log.info("sync.preparing", pair_id=pair_id,
              source=str(source_folder), copy=str(copy_folder))

    _log.info("sync.loading_ignore_rules")
    rules = load_for_pair(
        source_folder=source_folder,
        copy_folder=copy_folder,
        extra_ignore_files=extra_ignore_files,
    )

    _log.info("sync.preflight.start", source=str(source_folder), copy=str(copy_folder))
    copy_ctx = resolve_git(copy_folder)
    pre = preflight_for_sync(
        source_folder=source_folder,
        copy_folder=copy_folder,
        copy_ctx=copy_ctx,
    )
    if not pre.ok:
        for blocker in pre.blockers:
            _log.error("sync.preflight.blocker", reason=blocker)
        raise PreflightError("\n".join(pre.blockers))
    for warning in pre.warnings:
        _log.warning("sync.preflight.warning", reason=warning)
    _log.info("sync.preflight.ok")

    _log.info("sync.diff.scanning_source", path=str(source_folder))
    _log.info("sync.diff.scanning_copy", path=str(copy_folder))
    diff_plan = diff(
        source_folder=source_folder,
        copy_folder=copy_folder,
        rules=rules,
        sample_rate=sample_rate,
    )
    _log.info(
        "sync.diff.done",
        adds=len(diff_plan.adds),
        modifies=len(diff_plan.modifies),
        quarantines=len(diff_plan.quarantines),
        sample_verified=diff_plan.sample_verified,
    )

    sync_id = syncs_repo.begin(writer, pair_id=pair_id)
    _log.info(
        "sync.start",
        sync_id=sync_id, pair_id=pair_id,
        source=str(source_folder), copy=str(copy_folder),
        adds=len(diff_plan.adds), modifies=len(diff_plan.modifies),
        quarantines=len(diff_plan.quarantines),
    )
    journal_mod.append(
        writer, sync_id=sync_id, action="plan",
        extra={"adds": len(diff_plan.adds), "modifies": len(diff_plan.modifies),
               "quarantines": len(diff_plan.quarantines)},
    )

    snapshot: Snapshot | None = None
    try:
        _log.info("sync.snapshot.start", pair_id=pair_id, copy=str(copy_folder))
        snapshot = snapshot_take(pair_id=pair_id, copy_folder=copy_folder)
        _log.info("sync.snapshot.written",
                  sync_id=sync_id, path=str(snapshot.path),
                  size_bytes=snapshot.size, sha256=snapshot.sha256[:12])
        blob_id = blobs_repo.insert(
            writer,
            kind="snapshot",
            path=snapshot.path,
            sha256=snapshot.sha256,
            size=snapshot.size,
        )
        syncs_repo.attach_snapshot(writer, sync_id=sync_id, snapshot_blob_id=blob_id)
        journal_mod.append(
            writer, sync_id=sync_id, action="snapshot",
            extra={"path": str(snapshot.path), "sha256": snapshot.sha256, "size": snapshot.size},
        )

        if diff_plan.is_noop:
            _log.info("sync.noop", sync_id=sync_id,
                      reason="source and copy are already in sync")
            journal_mod.append(writer, sync_id=sync_id, action="close",
                               extra={"reason": "noop"})
            syncs_repo.finalize(writer, sync_id=sync_id, status="ok")
            _append_receipt(writer, sync_id=sync_id, snapshot=snapshot)
            return SyncOutcome(
                sync_id=sync_id, status="ok",
                snapshot=snapshot, diff_plan=diff_plan,
                files_added=0, files_modified=0, files_quarantined=0,
            )

        plan = _build_plan(sync_id=sync_id, diff_plan=diff_plan,
                           source_folder=source_folder, copy_folder=copy_folder)
        _log.info("sync.apply.start",
                  sync_id=sync_id,
                  total_steps=len(plan.steps),
                  writes=plan.write_count,
                  quarantines=plan.quarantine_count)

        # Apply the plan.
        for idx, step in enumerate(plan.steps, start=1):
            _apply_step(step, writer=writer, sync_id=sync_id, step_no=idx,
                        total=len(plan.steps))

        _log.info("sync.apply.done", sync_id=sync_id, steps=len(plan.steps))

        # Verify-after-sync on every changed file.
        _log.info("sync.verify.start", sync_id=sync_id, files=plan.write_count)
        _verify_after(plan, writer=writer, sync_id=sync_id, source_folder=source_folder)
        _log.info("sync.verify.ok", sync_id=sync_id, files=plan.write_count)

        journal_mod.append(writer, sync_id=sync_id, action="close",
                           extra={"reason": "ok"})
        _log.info("sync.finalize", sync_id=sync_id)
        syncs_repo.finalize(
            writer, sync_id=sync_id, status="ok",
            files_added=len(diff_plan.adds),
            files_modified=len(diff_plan.modifies),
            files_quarantined=len(diff_plan.quarantines),
        )
        _append_receipt(writer, sync_id=sync_id, snapshot=snapshot)
        _log.info("sync.ok", sync_id=sync_id,
                  added=len(diff_plan.adds), modified=len(diff_plan.modifies),
                  quarantined=len(diff_plan.quarantines))
        return SyncOutcome(
            sync_id=sync_id, status="ok",
            snapshot=snapshot, diff_plan=diff_plan,
            files_added=len(diff_plan.adds),
            files_modified=len(diff_plan.modifies),
            files_quarantined=len(diff_plan.quarantines),
        )

    except Exception as exc:
        _log.error("sync.failed", sync_id=sync_id, error=str(exc), error_type=type(exc).__name__)
        journal_mod.append(writer, sync_id=sync_id, action="close",
                           extra={"reason": "failed", "error": str(exc)})
        syncs_repo.finalize(writer, sync_id=sync_id, status="failed")
        return SyncOutcome(
            sync_id=sync_id, status="failed",
            snapshot=snapshot, diff_plan=diff_plan,
            files_added=0, files_modified=0, files_quarantined=0,
        )


def _build_plan(
    *, sync_id: str, diff_plan: DiffPlan, source_folder: Path, copy_folder: Path,
) -> TransactionPlan:
    steps: list[TransactionStep] = []
    for changed in (*diff_plan.adds, *diff_plan.modifies):
        src_abs = source_folder / changed.rel_path
        cpy_abs = copy_folder / changed.rel_path
        steps.append(TransactionStep(
            kind=StepKind.WRITE,
            rel_path=changed.rel_path,
            copy_abs_path=cpy_abs,
            source_abs_path=src_abs,
        ))
    for changed in diff_plan.quarantines:
        cpy_abs = copy_folder / changed.rel_path
        steps.append(TransactionStep(
            kind=StepKind.QUARANTINE,
            rel_path=changed.rel_path,
            copy_abs_path=cpy_abs,
            source_abs_path=None,
        ))
    return TransactionPlan(sync_id=sync_id, steps=tuple(steps))


def _apply_step(
    step: TransactionStep, *, writer: DbWriter, sync_id: str,
    step_no: int = 0, total: int = 0,
) -> None:
    if step.kind == StepKind.WRITE:
        prev_hash = _hash_if_exists(step.copy_abs_path)
        new_hash = xxh64_file(step.source_abs_path) if step.source_abs_path else None
        action = "write" if prev_hash is not None else "add"
        _log.info(f"sync.apply.{action}",
                  sync_id=sync_id, step=f"{step_no}/{total}",
                  rel_path=step.rel_path)
        journal_mod.append(
            writer, sync_id=sync_id, action="write",
            rel_path=step.rel_path, prev_hash=prev_hash, new_hash=new_hash,
        )
        _atomic_write(src=step.source_abs_path, dest=step.copy_abs_path)  # type: ignore[arg-type]
    elif step.kind == StepKind.QUARANTINE:
        prev_hash = _hash_if_exists(step.copy_abs_path)
        _log.info("sync.apply.quarantine",
                  sync_id=sync_id, step=f"{step_no}/{total}",
                  rel_path=step.rel_path)
        journal_mod.append(
            writer, sync_id=sync_id, action="quarantine",
            rel_path=step.rel_path, prev_hash=prev_hash,
        )
        move_to_quarantine(
            sync_id=sync_id,
            file_path=step.copy_abs_path,
            rel_path=step.rel_path,
        )


def _atomic_write(*, src: Path, dest: Path) -> None:
    """Stage to ``<dest>.rabbitsync.tmp``, fsync, atomic rename."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = temp_path_for(dest)
    with src.open("rb") as in_fh, tmp.open("wb") as out_fh:
        while True:
            chunk = in_fh.read(1024 * 1024)
            if not chunk:
                break
            out_fh.write(chunk)
        out_fh.flush()
        os.fsync(out_fh.fileno())
    os.replace(tmp, dest)


def _verify_after(
    plan: TransactionPlan, *, writer: DbWriter, sync_id: str, source_folder: Path,
) -> None:
    for step in plan.steps:
        if step.kind != StepKind.WRITE or step.source_abs_path is None:
            continue
        src_hash = xxh64_file(step.source_abs_path)
        cpy_hash = xxh64_file(step.copy_abs_path)
        if src_hash != cpy_hash:
            raise RuntimeError(
                f"verify-after-sync mismatch on {step.rel_path}: "
                f"source={src_hash} copy={cpy_hash}"
            )
    journal_mod.append(writer, sync_id=sync_id, action="verify",
                       extra={"checked": plan.write_count})
    _ = source_folder  # reserved for future source-side spot checks


def _hash_if_exists(p: Path) -> str | None:
    try:
        return xxh64_file(p)
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return None


def _append_receipt(writer: DbWriter, *, sync_id: str, snapshot: Snapshot | None) -> None:
    entries = journal_mod.entries_for(writer, sync_id)
    h = hashlib.sha256()
    for e in entries:
        h.update(f"{e.seq}\x00{e.action}\x00{e.rel_path or ''}\x00{e.new_hash or ''}\x00{e.ts}\n".encode())
    journal_hash = h.hexdigest()
    snapshot_hash = snapshot.sha256 if snapshot else None
    receipts_repo.append(
        writer,
        sync_id=sync_id,
        snapshot_hash=snapshot_hash,
        journal_hash=journal_hash,
        payload={"entry_count": len(entries)},
    )


# Re-hash a snapshot blob from disk by streaming it. Convenience for callers.
def snapshot_blob_sha(path: Path) -> str:
    return sha256_file(path)


__all__ = ["SyncOutcome", "perform", "snapshot_blob_sha"]
