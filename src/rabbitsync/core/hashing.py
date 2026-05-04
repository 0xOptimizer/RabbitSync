"""File hashing for sync diff and verify-after.

xxhash is used for the per-file content hash (fast, deterministic, not
cryptographic). SHA-256 is used separately by the blobs subsystem for
snapshot/quarantine integrity (where cryptographic strength matters).

Hashing is parallelized via :class:`concurrent.futures.ProcessPoolExecutor`
for large change sets; small batches run inline to avoid pool startup cost.
"""

from __future__ import annotations

import hashlib
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import xxhash

# Reading in 1 MiB chunks balances syscall overhead vs RAM use; xxhash itself
# happily streams arbitrary chunk sizes.
_CHUNK = 1024 * 1024

# Threshold below which we don't bother spinning up a worker pool — the pool
# fork/spawn cost dominates for small batches.
_INLINE_THRESHOLD = 32


def xxh64_file(path: Path) -> str:
    """Return the 16-char hex xxh64 of the file at ``path``."""
    h = xxhash.xxh64()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of the file at ``path``."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def xxh64_many(paths: list[Path]) -> dict[Path, str]:
    """Return ``{path: hex-xxh64}`` for every path.

    Runs in-process for small batches; uses a process pool for large ones.
    Missing files are silently omitted from the result.
    """
    if not paths:
        return {}
    if len(paths) <= _INLINE_THRESHOLD:
        out: dict[Path, str] = {}
        for p in paths:
            try:
                out[p] = xxh64_file(p)
            except OSError:
                continue
        return out

    workers = max(1, _process_count())
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_safe_xxh64_str, [str(p) for p in paths]))
    out = {}
    for p, h in zip(paths, results, strict=True):
        if h is not None:
            out[p] = h
    return out


def _safe_xxh64_str(path_str: str) -> str | None:
    """Worker entry point: returns hex digest or None on failure."""
    try:
        return xxh64_file(Path(path_str))
    except OSError:
        return None


def _process_count() -> int:
    """Pick a reasonable parallelism level.

    Uses Python 3.13's ``os.process_cpu_count`` (CPU-aware, honors cgroups
    on Linux and job objects on Windows), capped at 8 to avoid drowning a
    laptop's I/O queue.
    """
    proc_count = getattr(os, "process_cpu_count", None)
    n = proc_count() if proc_count is not None else (os.cpu_count() or 1)
    return min(8, max(1, n or 1))


__all__ = ["sha256_file", "xxh64_file", "xxh64_many"]
