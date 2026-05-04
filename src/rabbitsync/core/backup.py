"""Pre-sync snapshots: streaming tar+zstd of the copy folder.

A snapshot is created before any sync write. The compressed tar lives at
``data/backups/<pair-id>/<iso-ts>.tar.zst`` and is registered in the
``blobs`` table (kind='snapshot') with its SHA-256 + size so the file's
integrity can be verified at restore time.

Streaming
---------
Both compression and tar generation stream — RAM stays bounded regardless of
copy size. ``zstandard.ZstdCompressor.stream_writer`` wraps the output file
handle, and Python's ``tarfile`` writes to that wrapper.

Restore
-------
Restoration is intentionally non-destructive: the snapshot is extracted into
``<copy>.restored-<ts>/`` (a sibling of the live copy folder). The user
inspects, then chooses to swap in. We never overwrite the live copy as part
of recovery.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import tarfile
from dataclasses import dataclass
from pathlib import Path

import zstandard as zstd

from rabbitsync.paths import backups_dir

_TAR_BUFFER = 256 * 1024  # bytes between flushes — keeps RAM bounded


@dataclass(frozen=True)
class Snapshot:
    """The result of taking a snapshot."""

    path: Path
    sha256: str
    size: int
    created_at: str
    pair_id: str


def take(*, pair_id: str, copy_folder: Path) -> Snapshot:
    """Create a snapshot of ``copy_folder``.

    The folder is walked depth-first; the produced tar preserves relative
    paths inside the folder (no absolute paths leak into the archive).
    """
    if not copy_folder.is_dir():
        raise FileNotFoundError(f"copy folder does not exist: {copy_folder}")

    pair_backups = backups_dir() / pair_id
    pair_backups.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = pair_backups / f"{ts}.tar.zst"

    sha = hashlib.sha256()
    size = 0

    cctx = zstd.ZstdCompressor(level=10, threads=-1)
    with out_path.open("wb") as fh:
        # Tee writes through the hash + size accounting, then through zstd to fh.
        accounting = _AccountingWriter(fh, sha, lambda n: None)
        with cctx.stream_writer(accounting, closefd=False) as zwriter:
            with tarfile.open(fileobj=zwriter, mode="w|", bufsize=_TAR_BUFFER) as tar:
                tar.add(str(copy_folder), arcname=".", recursive=True)
        # accounting was wrapping fh; once we close zwriter the bytes have
        # all flushed through. The on-disk size is fh.tell().
        size = fh.tell()

    # Compute sha256 of the on-disk file (post-compression).
    sha = hashlib.sha256()
    with out_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_TAR_BUFFER), b""):
            sha.update(chunk)

    return Snapshot(
        path=out_path,
        sha256=sha.hexdigest(),
        size=size,
        created_at=_dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        pair_id=pair_id,
    )


def restore_to_sibling(snapshot_path: Path, *, copy_folder: Path) -> Path:
    """Extract a snapshot into a sibling directory, never overwriting copy.

    Returns the directory the snapshot was extracted into.
    """
    if not snapshot_path.is_file():
        raise FileNotFoundError(f"snapshot not found: {snapshot_path}")
    ts = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    target = copy_folder.with_name(copy_folder.name + f".restored-{ts}")
    if target.exists():
        raise FileExistsError(f"restore target already exists: {target}")
    target.mkdir(parents=True, exist_ok=False)

    dctx = zstd.ZstdDecompressor()
    with snapshot_path.open("rb") as fh, dctx.stream_reader(fh) as zreader:
        # tarfile needs a seekable-or-streamable file; stream_reader is
        # streamable. Use mode='r|' for streaming (non-random) access.
        with tarfile.open(fileobj=zreader, mode="r|") as tar:
            tar.extractall(path=str(target), filter="data")
    return target


def verify(snapshot_path: Path, *, expected_sha256: str) -> bool:
    """Re-hash a snapshot file and compare against the recorded SHA-256."""
    if not snapshot_path.is_file():
        return False
    sha = hashlib.sha256()
    with snapshot_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_TAR_BUFFER), b""):
            sha.update(chunk)
    return sha.hexdigest() == expected_sha256


class _AccountingWriter(io.RawIOBase):
    """File-like wrapper that updates a hash and a counter on every write."""

    def __init__(self, inner, sha, _on_bytes):
        super().__init__()
        self._inner = inner
        self._sha = sha
        self._n = 0

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:  # type: ignore[override]
        n = self._inner.write(b)
        self._sha.update(b)
        self._n += n
        return n

    def flush(self) -> None:
        self._inner.flush()


__all__ = ["Snapshot", "restore_to_sibling", "take", "verify"]
