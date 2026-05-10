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
import os
import tarfile
from dataclasses import dataclass
from pathlib import Path

import zstandard as zstd

from rabbitsync.paths import backups_dir

_TAR_BUFFER = 256 * 1024  # bytes between flushes — keeps RAM bounded
_ZSTD_LEVEL = 3            # ephemeral snapshots: prioritize speed over ratio


# Path fragments that contribute almost no recovery value but a lot of bytes.
# - .git/objects/pack: immutable binary packs git can rebuild from refs.
# - .git/objects/info: indexes git regenerates from packs.
# - .git/lfs / .git/annex: huge per-blob caches; if the user uses these we'd
#   double the snapshot for no gain.
_SNAPSHOT_EXCLUDE_FRAGMENTS: tuple[str, ...] = (
    "/.git/objects/pack/",
    "/.git/objects/info/",
    "/.git/lfs/",
    "/.git/annex/",
)


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
    paths inside the folder (no absolute paths leak into the archive). The
    SHA-256 of the on-disk compressed bytes is computed in a single streaming
    pass so the file is never read twice. ``.git/objects/pack/*`` and similar
    immutable bulk caches are excluded — git can rebuild them from refs and
    skipping them keeps snapshots small and fast.
    """
    if not copy_folder.is_dir():
        raise FileNotFoundError(f"copy folder does not exist: {copy_folder}")

    pair_backups = backups_dir() / pair_id
    pair_backups.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = pair_backups / f"{ts}.tar.zst"

    # Hash the on-disk compressed bytes inline as they're written. This is
    # the canonical SHA — no second-pass re-read.
    sha = hashlib.sha256()

    cctx = zstd.ZstdCompressor(level=_ZSTD_LEVEL, threads=-1)
    with out_path.open("wb") as fh:
        accounting = _AccountingWriter(fh, sha)
        with cctx.stream_writer(accounting, closefd=False) as zwriter:
            with tarfile.open(fileobj=zwriter, mode="w|", bufsize=_TAR_BUFFER) as tar:
                tar.add(
                    str(copy_folder),
                    arcname=".",
                    recursive=True,
                    filter=_snapshot_filter,
                )

    return Snapshot(
        path=out_path,
        sha256=sha.hexdigest(),
        size=accounting.bytes_written,
        created_at=_dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        pair_id=pair_id,
    )


def _snapshot_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Drop bulky-but-recoverable paths from the archive."""
    name = "/" + info.name.replace("\\", "/").lstrip("/")
    for fragment in _SNAPSHOT_EXCLUDE_FRAGMENTS:
        if fragment in name:
            return None
    return info


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
    """File-like wrapper that updates a hash and a counter on every write.

    Sits between :class:`zstd.ZstdCompressor.stream_writer` and the on-disk
    file handle so the SHA-256 it accumulates is the hash of the compressed
    bytes — exactly what's stored in the ``blobs`` table for verification.
    """

    def __init__(self, inner, sha):
        super().__init__()
        self._inner = inner
        self._sha = sha
        self._n = 0

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:  # type: ignore[override]
        n = self._inner.write(b)
        # ``b`` may be a memoryview / bytearray; bytes(...) is cheap and gives
        # hashlib a safe input even when n < len(b) (rare on regular files).
        view = bytes(b)[:n] if n is not None and n != len(b) else b
        self._sha.update(view)
        self._n += n
        return n

    def flush(self) -> None:
        self._inner.flush()

    @property
    def bytes_written(self) -> int:
        return self._n


_ = os  # reserved for future use (e.g. fadvise on Linux)


__all__ = ["Snapshot", "restore_to_sibling", "take", "verify"]
