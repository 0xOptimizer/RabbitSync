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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rabbitsync.core import commit_messages
from rabbitsync.core.backup import Snapshot, take as snapshot_take, write_manifest
from rabbitsync.core.diff import DiffPlan, diff
from rabbitsync.core.git import GitCommandError, GitRunner
from rabbitsync.core.git_info import head_sha as git_head_sha, status as git_status
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
    copy_commit_sha: str | None = None
    pushed: bool = False
    commit_message: str | None = None


@dataclass(frozen=True)
class ProgressEvent:
    """One progress tick from the sync engine.

    ``phase`` is the high-level stage (preflight/diff/snapshot/apply/verify/
    commit/push/done). For per-file phases ``step_no`` / ``total`` count files
    and ``rel_path`` names the file currently being acted on.
    """

    phase: str
    step_no: int = 0
    total: int = 0
    rel_path: str | None = None


ProgressCallback = Callable[[ProgressEvent], None]


def _emit(cb: ProgressCallback | None, ev: ProgressEvent) -> None:
    if cb is None:
        return
    try:
        cb(ev)
    except Exception:  # noqa: BLE001 -- progress is best-effort, never fatal
        pass


def perform(
    *,
    pair_id: str,
    source_folder: Path,
    copy_folder: Path,
    writer: DbWriter,
    extra_ignore_files: tuple[Path, ...] = (),
    sample_rate: float = 0.01,
    commit_on_sync: bool = False,
    auto_push: bool = False,
    target_branch: str | None = None,
    progress_cb: ProgressCallback | None = None,
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
    _emit(progress_cb, ProgressEvent(phase="preflight"))
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
    _emit(progress_cb, ProgressEvent(phase="diff"))
    diff_plan = diff(
        source_folder=source_folder,
        copy_folder=copy_folder,
        rules=rules,
        sample_rate=sample_rate,
        pair_id=pair_id,
        writer=writer,
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

    # Fast-path noop BEFORE taking a snapshot. A snapshot is a tar+zstd of the
    # entire copy folder; doing it just to back up "nothing changed" is what
    # made repeat-syncs feel slow on big repos.
    if diff_plan.is_noop:
        _log.info("sync.noop", sync_id=sync_id,
                  reason="source and copy are already in sync")
        journal_mod.append(writer, sync_id=sync_id, action="close",
                           extra={"reason": "noop"})
        syncs_repo.finalize(writer, sync_id=sync_id, status="ok")
        _append_receipt(writer, sync_id=sync_id, snapshot=None)
        _emit(progress_cb, ProgressEvent(phase="done"))
        return SyncOutcome(
            sync_id=sync_id, status="ok",
            snapshot=None, diff_plan=diff_plan,
            files_added=0, files_modified=0, files_quarantined=0,
        )

    # Selective snapshot: only files we're about to overwrite need backing up.
    # Added files don't (rollback = delete); quarantined files don't (the
    # quarantine dir IS the backup). If there are no modifies, skip snapshot
    # entirely — this is the path that turned a 90%-of-runtime snapshot of
    # the whole copy folder into a no-op for adds-only or quarantines-only
    # syncs.
    modified_paths = [m.rel_path for m in diff_plan.modifies]
    snapshot: Snapshot | None = None
    try:
        if modified_paths:
            _log.info("sync.snapshot.start",
                      pair_id=pair_id, copy=str(copy_folder),
                      kind="selective", files=len(modified_paths))
            _emit(progress_cb, ProgressEvent(phase="snapshot"))
            snapshot = snapshot_take(
                pair_id=pair_id,
                copy_folder=copy_folder,
                include_paths=modified_paths,
            )
            _log.info("sync.snapshot.written",
                      sync_id=sync_id, path=str(snapshot.path),
                      size_bytes=snapshot.size, sha256=snapshot.sha256[:12])
            # Sidecar manifest so a future rollback knows the full picture:
            # which files to delete (adds), which to extract from the tar
            # (modifies), which to un-quarantine.
            manifest = {
                "sync_id": sync_id,
                "pair_id": pair_id,
                "snapshot_kind": "selective",
                "snapshot_sha256": snapshot.sha256,
                "snapshot_path": str(snapshot.path),
                "created_at": snapshot.created_at,
                "adds": [a.rel_path for a in diff_plan.adds],
                "modifies": modified_paths,
                "quarantines": [q.rel_path for q in diff_plan.quarantines],
            }
            try:
                write_manifest(snapshot.path, manifest)
            except OSError as exc:
                _log.warning("sync.snapshot.manifest_failed",
                             sync_id=sync_id, error=str(exc))
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
                extra={"path": str(snapshot.path), "sha256": snapshot.sha256,
                       "size": snapshot.size, "kind": "selective",
                       "files": len(modified_paths)},
            )
        else:
            _log.info("sync.snapshot.skipped",
                      sync_id=sync_id,
                      reason="no modifies — adds/quarantines don't need a snapshot")
            journal_mod.append(
                writer, sync_id=sync_id, action="snapshot",
                extra={"skipped": True,
                       "reason": "no modifies — adds/quarantines don't need a snapshot"},
            )

        plan = _build_plan(sync_id=sync_id, diff_plan=diff_plan,
                           source_folder=source_folder, copy_folder=copy_folder)
        _log.info("sync.apply.start",
                  sync_id=sync_id,
                  total_steps=len(plan.steps),
                  writes=plan.write_count,
                  quarantines=plan.quarantine_count)

        # Apply the plan, caching every source xxh64 so verify-after doesn't
        # have to re-read source from disk. Journal entries are buffered into
        # batches so we don't pay one fsynced round-trip per file op.
        source_hash_cache: dict[str, str] = {}
        total_steps = len(plan.steps)
        with journal_mod.JournalBatch(writer, sync_id) as batch:
            for idx, step in enumerate(plan.steps, start=1):
                _emit(progress_cb, ProgressEvent(
                    phase="apply", step_no=idx, total=total_steps,
                    rel_path=step.rel_path,
                ))
                _apply_step(
                    step, sync_id=sync_id, journal_batch=batch,
                    step_no=idx, total=total_steps,
                    source_hash_cache=source_hash_cache,
                )

        _log.info("sync.apply.done", sync_id=sync_id, steps=len(plan.steps))

        # Verify-after-sync on every changed file (uses the cached source hashes).
        _log.info("sync.verify.start", sync_id=sync_id, files=plan.write_count)
        _emit(progress_cb, ProgressEvent(phase="verify", total=plan.write_count))
        _verify_after(
            plan, writer=writer, sync_id=sync_id, source_folder=source_folder,
            source_hash_cache=source_hash_cache,
        )
        _log.info("sync.verify.ok", sync_id=sync_id, files=plan.write_count)

        # Optional commit + push on the copy side.
        copy_commit_sha: str | None = None
        commit_message: str | None = None
        pushed = False
        if commit_on_sync:
            try:
                _emit(progress_cb, ProgressEvent(phase="commit"))
                copy_commit_sha, commit_message = _commit_on_copy(
                    sync_id=sync_id,
                    copy_folder=copy_folder,
                    source_folder=source_folder,
                    diff_plan=diff_plan,
                    target_branch=target_branch,
                    writer=writer,
                )
                if copy_commit_sha is not None and auto_push:
                    _emit(progress_cb, ProgressEvent(phase="push"))
                    pushed = _push_copy(
                        sync_id=sync_id, copy_folder=copy_folder,
                        target_branch=target_branch, writer=writer,
                    )
            except Exception as exc:  # noqa: BLE001
                # Commit/push failure is loud but does NOT roll back the sync —
                # the working tree is already converged + verified, the snapshot
                # is intact, the user can retry the commit manually.
                _log.error("sync.commit.failed",
                           sync_id=sync_id, error=str(exc),
                           error_type=type(exc).__name__)

        journal_mod.append(writer, sync_id=sync_id, action="close",
                           extra={"reason": "ok"})
        _log.info("sync.finalize", sync_id=sync_id)
        source_sha = _safe_head_sha(source_folder)
        syncs_repo.finalize(
            writer, sync_id=sync_id, status="ok",
            files_added=len(diff_plan.adds),
            files_modified=len(diff_plan.modifies),
            files_quarantined=len(diff_plan.quarantines),
            source_sha=source_sha,
            copy_commit_sha=copy_commit_sha,
        )
        _append_receipt(writer, sync_id=sync_id, snapshot=snapshot)
        _log.info("sync.ok", sync_id=sync_id,
                  added=len(diff_plan.adds), modified=len(diff_plan.modifies),
                  quarantined=len(diff_plan.quarantines),
                  commit=copy_commit_sha[:7] if copy_commit_sha else None,
                  pushed=pushed)
        _emit(progress_cb, ProgressEvent(phase="done"))
        return SyncOutcome(
            sync_id=sync_id, status="ok",
            snapshot=snapshot, diff_plan=diff_plan,
            files_added=len(diff_plan.adds),
            files_modified=len(diff_plan.modifies),
            files_quarantined=len(diff_plan.quarantines),
            copy_commit_sha=copy_commit_sha,
            pushed=pushed,
            commit_message=commit_message,
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
    step: TransactionStep, *, sync_id: str,
    journal_batch: journal_mod.JournalBatch,
    step_no: int = 0, total: int = 0,
    source_hash_cache: dict[str, str] | None = None,
) -> None:
    if step.kind == StepKind.WRITE:
        new_hash: str | None = None
        if step.source_abs_path is not None:
            new_hash = xxh64_file(step.source_abs_path)
            if source_hash_cache is not None:
                source_hash_cache[step.rel_path] = new_hash
        _log.info("sync.apply.write",
                  sync_id=sync_id, step=f"{step_no}/{total}",
                  rel_path=step.rel_path)
        journal_batch.append("write", step.rel_path, new_hash=new_hash)
        _atomic_write(src=step.source_abs_path, dest=step.copy_abs_path)  # type: ignore[arg-type]
    elif step.kind == StepKind.QUARANTINE:
        _log.info("sync.apply.quarantine",
                  sync_id=sync_id, step=f"{step_no}/{total}",
                  rel_path=step.rel_path)
        journal_batch.append("quarantine", step.rel_path)
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
    source_hash_cache: dict[str, str] | None = None,
) -> None:
    """Re-hash the destination of every WRITE and assert it matches source.

    The source hash is read from ``source_hash_cache`` (populated during the
    apply phase) so we don't re-read source from disk — source hasn't changed
    between apply and verify, and the source-manifest-stable check (if added
    later) covers the editor-mid-sync race separately.
    """
    cache = source_hash_cache or {}
    for step in plan.steps:
        if step.kind != StepKind.WRITE or step.source_abs_path is None:
            continue
        src_hash = cache.get(step.rel_path)
        if src_hash is None:
            # Cache miss is unexpected (apply runs before verify); fall back
            # to re-reading rather than skip the safety check.
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


def _commit_on_copy(
    *,
    sync_id: str,
    copy_folder: Path,
    source_folder: Path,
    diff_plan: DiffPlan,
    target_branch: str | None,
    writer: DbWriter,
) -> tuple[str | None, str | None]:
    """Stage all changes in copy and commit with an auto-generated message.

    Returns ``(commit_sha, commit_message)`` on success; ``(None, None)`` if
    there were no changes to commit. Refuses to commit when copy isn't a git
    repo (returns None silently — the diff has already been written to disk).
    """
    copy_ctx = resolve_git(copy_folder)
    if not copy_ctx.has_git or copy_ctx.git_root is None:
        _log.info("sync.commit.skipped",
                  sync_id=sync_id, reason="copy is not a git repo")
        return None, None

    runner = GitRunner(copy_ctx.git_root)

    # Optionally switch to the target branch first. Refuse if dirty conflicts
    # would arise — the user can resolve manually.
    if target_branch:
        cur_status = git_status(copy_ctx)
        cur_branch = cur_status.branch if cur_status is not None else None
        if cur_branch != target_branch:
            _log.info("sync.commit.checkout",
                      sync_id=sync_id, branch=target_branch,
                      from_branch=cur_branch)
            try:
                runner.run(["checkout", target_branch], check=True, timeout=30)
            except GitCommandError as exc:
                _log.warning("sync.commit.checkout_failed",
                             sync_id=sync_id, error=str(exc))
                # Keep going on the current branch rather than abort.

    _log.info("sync.commit.staging", sync_id=sync_id, subpath=copy_ctx.subpath or ".")
    add_target = copy_ctx.subpath if copy_ctx.subpath else "."
    runner.run(["add", "-A", "--", add_target], check=True, timeout=120)

    # Anything staged?
    porcelain = runner.run(["status", "--porcelain=v2"], check=False, timeout=15)
    has_staged = any(
        line.startswith(("1 ", "2 ", "u "))
        and len(line) > 2 and line[2] != "."  # index status non-blank
        for line in porcelain.stdout.splitlines()
    )
    if not has_staged:
        _log.info("sync.commit.nothing_staged",
                  sync_id=sync_id,
                  reason="all working-tree changes already committed by another process")
        return None, None

    # Build the commit message.
    source_ctx = resolve_git(source_folder)
    src_sha = git_head_sha(source_ctx) if source_ctx.has_git else None
    src_status = git_status(source_ctx) if source_ctx.has_git else None
    src_branch = src_status.branch if src_status is not None else None
    body = commit_messages.for_sync(
        diff_plan, source_branch=src_branch, source_sha=src_sha,
    )
    message = commit_messages.render(body)
    if not commit_messages.is_safe_for_argv(message):
        message = commit_messages.render(commit_messages.for_sync(diff_plan))

    _log.info("sync.commit.committing", sync_id=sync_id, message=message)
    try:
        runner.run(["commit", "-m", message], check=True, timeout=60)
    except GitCommandError as exc:
        _log.error("sync.commit.commit_failed", sync_id=sync_id, error=str(exc))
        raise

    new_sha_result = runner.run(["rev-parse", "HEAD"], check=False, timeout=15)
    new_sha = new_sha_result.stdout.strip() or None
    journal_mod.append(
        writer, sync_id=sync_id, action="commit",
        extra={"sha": new_sha, "message": message},
    )
    _log.info("sync.commit.ok",
              sync_id=sync_id, sha=new_sha[:7] if new_sha else None)
    return new_sha, message


def _push_copy(
    *, sync_id: str, copy_folder: Path,
    target_branch: str | None, writer: DbWriter,
) -> bool:
    """Push the current branch in copy. Returns True on success."""
    copy_ctx = resolve_git(copy_folder)
    if not copy_ctx.has_git or copy_ctx.git_root is None:
        return False
    runner = GitRunner(copy_ctx.git_root)

    s = git_status(copy_ctx)
    branch = (s.branch if s is not None else None) or target_branch
    args: list[str] = ["push", "--progress"]
    if s is not None and s.upstream is None and branch:
        args += ["--set-upstream", "origin", branch]

    _log.info("sync.push.start", sync_id=sync_id, branch=branch)
    try:
        runner.run(args, check=True, timeout=300)
    except GitCommandError as exc:
        _log.error("sync.push.failed", sync_id=sync_id, error=str(exc))
        raise
    journal_mod.append(
        writer, sync_id=sync_id, action="push",
        extra={"branch": branch},
    )
    _log.info("sync.push.ok", sync_id=sync_id, branch=branch)
    return True


def _safe_head_sha(folder: Path) -> str | None:
    try:
        ctx = resolve_git(folder)
    except (FileNotFoundError, NotADirectoryError, OSError):
        return None
    if not ctx.has_git:
        return None
    return git_head_sha(ctx)


# Re-hash a snapshot blob from disk by streaming it. Convenience for callers.
def snapshot_blob_sha(path: Path) -> str:
    return sha256_file(path)


__all__ = ["ProgressCallback", "ProgressEvent", "SyncOutcome", "perform", "snapshot_blob_sha"]
