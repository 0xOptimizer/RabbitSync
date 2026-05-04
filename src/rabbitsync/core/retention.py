"""Retention sweeps for snapshots, quarantine, logs, journals, pipeline runs.

Hard rule: only RabbitSync's own bookkeeping is unlinked here. User-repo
files are *never* removed by retention — only by the soft-delete quarantine
in :mod:`rabbitsync.core.quarantine`.
"""

from __future__ import annotations

import datetime as _dt
import shutil
from dataclasses import dataclass
from pathlib import Path

from rabbitsync.config.store import Settings, load_settings
from rabbitsync.db.connection import ConnectionFactory, closing
from rabbitsync.db.writer import DbWriter
from rabbitsync.paths import backups_dir, logs_dir, pipelines_dir, quarantine_dir


@dataclass(frozen=True)
class SweepResult:
    snapshots_removed: int
    snapshots_freed_bytes: int
    quarantine_removed: int
    quarantine_freed_bytes: int
    logs_removed: int
    pipeline_runs_removed: int
    journals_removed: int


def sweep(
    writer: DbWriter | None,
    *,
    settings: Settings | None = None,
    factory: ConnectionFactory | None = None,
) -> SweepResult:
    """Run a full retention sweep and return what was freed."""
    s = settings if settings is not None else load_settings(factory=factory)

    snap_removed, snap_bytes = _sweep_snapshots(s, writer=writer, factory=factory)
    quar_removed, quar_bytes = _sweep_quarantine(s)
    logs_removed = _sweep_logs(s)
    pipes_removed = _sweep_pipeline_runs(s)
    jour_removed = _sweep_journals(s, writer=writer)

    return SweepResult(
        snapshots_removed=snap_removed,
        snapshots_freed_bytes=snap_bytes,
        quarantine_removed=quar_removed,
        quarantine_freed_bytes=quar_bytes,
        logs_removed=logs_removed,
        pipeline_runs_removed=pipes_removed,
        journals_removed=jour_removed,
    )


def _sweep_snapshots(
    s: Settings, *, writer: DbWriter | None, factory: ConnectionFactory | None,
) -> tuple[int, int]:
    """Apply (keep last N + last D days, max GB per pair)."""
    f = factory if factory is not None else ConnectionFactory()
    cutoff = _dt.datetime.now(_dt.UTC) - _dt.timedelta(days=s.snapshot_keep_days)
    removed = 0
    freed = 0

    with closing(f.reader()) as conn:
        rows = list(conn.execute(
            "SELECT id, path, sha256, size, created_at FROM blobs "
            "WHERE kind = 'snapshot' ORDER BY created_at DESC;"
        ))

    by_pair: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        path = Path(str(row["path"]))
        # Snapshot path layout: data/backups/<pair-id>/<ts>.tar.zst
        try:
            pair_id = path.parent.name
        except IndexError:
            continue
        by_pair.setdefault(pair_id, []).append({
            "id": int(row["id"]),
            "path": path,
            "size": int(row["size"]),
            "created_at": row["created_at"],
        })

    max_bytes = s.snapshot_max_gb * 1024 * 1024 * 1024
    for _pair, snaps in by_pair.items():
        keep_count = s.snapshot_keep_count
        running = 0
        survivors: list[dict[str, object]] = []
        for entry in snaps:
            created = _parse_iso(entry["created_at"])  # type: ignore[arg-type]
            entry_size = int(entry["size"])  # type: ignore[arg-type]
            time_eligible = created is not None and created < cutoff
            count_eligible = len(survivors) >= keep_count
            size_eligible = (running + entry_size) > max_bytes
            if time_eligible and count_eligible:
                _delete_snapshot(entry["id"], entry["path"], writer=writer)  # type: ignore[arg-type]
                removed += 1
                freed += entry_size
                continue
            if size_eligible and count_eligible:
                _delete_snapshot(entry["id"], entry["path"], writer=writer)  # type: ignore[arg-type]
                removed += 1
                freed += entry_size
                continue
            survivors.append(entry)
            running += entry_size

    return removed, freed


def _delete_snapshot(blob_id: int, path: Path, *, writer: DbWriter | None) -> None:
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            pass
    if writer is not None:
        from rabbitsync.db.repositories import blobs_repo

        blobs_repo.delete(blob_id, writer)


def _sweep_quarantine(s: Settings) -> tuple[int, int]:
    """Remove quarantine entries older than the snapshot-keep window."""
    cutoff = _dt.datetime.now(_dt.UTC) - _dt.timedelta(days=s.snapshot_keep_days)
    removed = 0
    freed = 0
    qroot = quarantine_dir()
    if not qroot.exists():
        return 0, 0
    for entry in qroot.iterdir():
        if not entry.is_dir():
            continue
        try:
            mtime = _dt.datetime.fromtimestamp(entry.stat().st_mtime, tz=_dt.UTC)
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        size = _tree_size(entry)
        try:
            shutil.rmtree(entry)
        except OSError:
            continue
        removed += 1
        freed += size
    return removed, freed


def _sweep_logs(s: Settings) -> int:
    """Keep at most ``log_keep_files`` JSONL log files."""
    log_root = logs_dir()
    files = sorted(log_root.glob("*.jsonl*"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for old in files[s.log_keep_files:]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _sweep_pipeline_runs(s: Settings) -> int:
    """Remove pipeline run dirs older than the snapshot-keep window."""
    cutoff = _dt.datetime.now(_dt.UTC) - _dt.timedelta(days=s.snapshot_keep_days)
    removed = 0
    proot = pipelines_dir()
    if not proot.exists():
        return 0
    for pair_dir in proot.iterdir():
        if not pair_dir.is_dir():
            continue
        for run_dir in pair_dir.iterdir():
            if not run_dir.is_dir():
                continue
            try:
                mtime = _dt.datetime.fromtimestamp(run_dir.stat().st_mtime, tz=_dt.UTC)
            except OSError:
                continue
            if mtime >= cutoff:
                continue
            try:
                shutil.rmtree(run_dir)
                removed += 1
            except OSError:
                pass
    return removed


def _sweep_journals(s: Settings, *, writer: DbWriter | None) -> int:
    """Remove journal_entries for syncs that finished more than 30 days ago."""
    if writer is None:
        return 0
    cutoff = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(days=30)).isoformat(timespec="seconds")

    def _do(conn) -> int:  # noqa: ANN001
        cur = conn.execute(
            "DELETE FROM journal_entries WHERE sync_id IN ("
            "  SELECT sync_id FROM syncs WHERE status != 'running' "
            "  AND finished_at IS NOT NULL AND finished_at < ?"
            ");",
            (cutoff,),
        )
        return int(cur.rowcount or 0)

    return writer.execute(_do)


def _backups_dir_used() -> int:
    return _tree_size(backups_dir())


def _tree_size(p: Path) -> int:
    total = 0
    try:
        for entry in p.rglob("*"):
            try:
                if entry.is_file():
                    total += entry.stat().st_size
            except OSError:
                continue
    except OSError:
        return 0
    return total


def _parse_iso(text: str) -> _dt.datetime | None:
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = _dt.datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.UTC)
        return dt
    except ValueError:
        return None


__all__ = ["SweepResult", "sweep"]
